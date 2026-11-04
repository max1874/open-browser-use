# Design

Three constraints decide everything else:

1. **Never touch the user's browser.** Agents get their own Chrome: its own
   `--user-data-dir`, its own CDP port (9333), its own process.
2. **Never take the user's screen.** Chrome is started with `open -g`, tabs are
   attached without being selected, and nothing calls `activate_tab()` on its own.
3. **Keep logins across sessions.** The profile lives in a fixed directory
   (`~/.local/share/agent-chrome`) and the browser stays up between sessions.

## The wrapper keeps the upstream name

browser-harness tells daemons apart by `BU_NAME`: one name, one daemon, one
attached tab. Upstream mentions it only for cloud browsers, so every local
session runs as `default` and they all drive the same tab. Worse, the `default`
daemon attaches to `pages[0]` of whatever Chrome it finds, which is the tab the
user is reading.

`bin/browser-harness` sits where uv puts the real launcher and `exec`s it after
setting two variables:

- `BU_NAME` from the agent's own session id: `CLAUDE_CODE_SESSION_ID` gives
  `cc-<first segment>`, `CODEX_THREAD_ID` gives `cx-<first segment>`.
- `BU_CDP_URL` pointing at the agent Chrome, after `bh-agent-chrome` has made
  sure it is running.

It keeps the name `browser-harness` on purpose. Every upstream document and
example says `browser-harness`; a wrapper called anything else is one an agent
copying an example will bypass. Anything that depends on an agent remembering a
flag fails the first time it forgets.

## Background input: focus emulation

CDP's `Input.dispatchMouseEvent` and `Input.dispatchKeyEvent` silently do
nothing when the target tab is not the selected tab of its window, or the window
is covered. No error; no event reaches the page. `Runtime.evaluate` and
`Input.insertText` keep working, which makes the failure look like a page bug.

The variable is the page's `visibilityState`, not macOS focus.
`Emulation.setFocusEmulationEnabled` flips it to `visible` for one CDP session
and restores trusted input without selecting the tab or raising the window.
Measured on Chrome 151, hidden tab:

```text
before   visibilityState=hidden    click events []                 press_key ''
after    visibilityState=visible   click events ["trusted=true"]   press_key 'Q'
```

`agent_helpers.py` arms it lazily on the first `cdp()` call (the daemon does not
exist yet when the helpers load), and disarms after `new_tab()`, `switch_tab()`
and `ensure_real_tab()`, because attaching to another target starts a new CDP
session and the setting belongs to the session.

Two traps found while testing this:

- **A broken helpers symlink disables the patch silently**: browser-harness
  skips a missing helpers file without a word. The wrapper warns when the link
  is dangling.
- **A live daemon hides the breakage.** The setting lives on the daemon's
  existing CDP session, so with the patch gone, clicks keep working until the
  daemon restarts. Test any load-time patch after restarting the daemon.

## Tab groups through an extension

CDP has no tab-group API, and `chrome.tabs` does not know CDP target ids. The
extension in `extension/` bridges them with `chrome.debugger.getTargets()`,
which lists both ids without attaching, so Chrome shows no "is debugging this
browser" bar.

`agent_helpers.py` reaches the extension's service worker as a CDP target and
calls functions on it with `Runtime.evaluate`: `bhGroup` after every
`new_tab()`, `bhNameSession`, `bhMarkTab`, `bhCloseSession`. The worker keeps
each session's group id and title in `chrome.storage.local`, so a group that
closed and comes back gets its name back. Tab marks live in
`chrome.storage.session` and survive navigation but not a Chrome restart.

Details that cost a debugging session each:

- **The worker sleeps.** It registers `tabs.onCreated`, so opening a tab wakes
  it; calls that do not open one open and close a background `about:blank`.
- **A reloaded extension can keep running its old worker script.** The worker
  publishes `self.bhApi`; the helpers compare it with their own `_GROUPS_API`
  and reload the extension on a mismatch, carrying the tab marks across.
  Change a worker function, bump both numbers.
- **Installed by hand, once per profile.** Branded Chrome ignores
  `--load-extension` since 137. CDP `Extensions.loadUnpacked` needs
  `--enable-unsafe-extension-debugging` and the extension is gone at the next
  launch; loaded that way and re-loaded on every call, it twice went missing
  from a running Chrome. chrome://extensions → "Load unpacked" persists across
  restarts without any flag (Chrome 156, 2026-11-04) and is the only install
  path. It cannot be scripted: a synthetic CDP drop reaches the page but not
  the browser ("No dragged path"), and `developerPrivate.loadDirectory` crashed
  Chrome. `bh-agent-chrome` reads the profile's Secure Preferences before a
  cold start and says so when the extension is missing.
- **Group colour** is a hash of `BU_NAME`, so a session keeps its colour.

## The pointer

`click_at_xy()` and `scroll()` write the target point onto `<html>` as an
attribute; the content script draws the pointer in a closed shadow root and
lets a 0.3 s CSS transition carry it there. The helper waits for the glide only
when the content script has announced itself and the point actually moved.
`capture_screenshot()` hides the pointer for the shot.

The pointer fades ten seconds after its last move. An earlier version marked the
favicon of the driven tab instead; the mark outlived the agent's turn, so it
said nothing about whether an agent was acting now, and Chrome saved every
marked icon into history as the site's real icon.

## Cleaning up after sessions

Nothing stops a daemon when its session ends, and agents call `close_session()`
only when they remember to. On one day there were 13 idle daemons, the oldest a
day old, and the agent Chrome held groups from sessions that ended 16 hours
earlier.

`bin/bh-reap` runs detached from the wrapper, at most every ten minutes. A
session has ended when its agent's own records say so:

| Name | Ended when |
|---|---|
| `cc-<id>` | no running `claude` process holds the session (`~/.claude/sessions/<pid>.json`) **and** its transcript is an hour old |
| `cx-<id>` | its Codex rollout file is a day old |
| anything else | the daemon started a day ago, or no daemon is left |

Claude Code needs both signals so neither alone can stop a live session. For an
ended session, unmarked tabs close at once and marked ones a day later. A
mistaken stop costs little: the session's next call starts a new daemon.

## Restarting the shared Chrome

Every session's tabs live in one Chrome, so restarting it closes work in
progress. It happened: a restart to load a new extension closed another
session's login page that the user was about to use. `bh-agent-chrome --restart`
now refuses while another session's daemon is alive, and only `--force`, after
the user agrees, goes ahead. Browser-wide settings count the same: turning off
tab sync once closed every session's groups, because Chrome removes
account-stored groups from the device when that data type is switched off.

## The fork

Two patches live on the `max` branch of
[max1874/browser-harness](https://github.com/max1874/browser-harness), each
because the helpers process cannot reach what it changes:

- The driven tab is marked with `<html data-browser-harness-agent>` instead of a
  🐴 prefix on `document.title`. Upstream's prefix changes the real page title,
  so anything that reads titles reads the horse too. The mark is set by the
  daemon process.
- A `release_target` daemon command: `mark_tab()` hands the tab over, so a
  daemon that stops no longer closes a tab the user was asked to look at.

## Data collection

browser-harness enables telemetry by default, and its CLI events skip the
redaction its other events get: a packet capture against v0.1.9 (August 2026,
not rechecked since) showed the full script, its
stdout and every helper argument, verbatim, including a URL with a token in it.
`install.sh` turns telemetry and recordings off and stops the per-run version
check.
