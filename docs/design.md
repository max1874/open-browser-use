# Design

Three constraints decide everything else:

1. **Never touch the user's browser.** Agents get their own Chrome: its own
   `--user-data-dir`, its own CDP port (9333), its own process.
2. **Never take the user's screen.** Chrome is started with `open -g` and no
   window (below), tabs are attached without being selected, and nothing calls
   `activate_tab()` on its own.
3. **Keep logins across sessions.** The profile lives in a fixed directory
   (`~/.local/share/open-browser-use/chrome`) and the browser stays up between sessions.

## Starting without taking the front

`open -g` does not keep Chrome in the background: Chrome activates itself when
it opens a window while it has none. Measured on Chrome 157, 2026-11-11, by
sampling the frontmost app every 0.1 s:

| Window opened by | Chrome in front |
|---|---|
| the startup window, `open -g` | 1.5–2 s |
| the startup window, `open -g -j` (hidden) | 0.5 s |
| `Target.createTarget`, no window yet, even `newWindow` + `background` | 1.5 s |
| the extension, `chrome.windows.create({focused: false})` | never |
| a background tab when a window exists | never |

So `open-browser-use start` launches with `--no-startup-window` and has the
extension's worker, which runs without a window, open the first one unfocused
before any daemon asks CDP for a tab. It does the same when Chrome is up but the
user has closed every window. Without the extension the daemon's first tab
still raises Chrome once.

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
- `BU_CDP_URL` pointing at the agent Chrome, after `open-browser-use start` has made
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

The daemon also attaches on its own when its CDP session drops, and the
helpers are not told. When it still moved to a replacement tab after its tab
closed, the page read `hidden` after `close_session()` and `new_tab()`, and
every click did nothing (Chrome 157, 2026-11-17). So `click_at_xy()`,
`press_key()` and `scroll()` read `visibilityState` before the input, in the
same evaluation as the guard below, and re-arm when it is `hidden`.

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
  Chrome. `open-browser-use` reads the profile's Secure Preferences before a
  cold start and says so when the extension is missing.
- **Group colour** is a hash of `BU_NAME`, so a session keeps its colour.

## Links and forms that open a tab

A `target="_blank"` link clicked by the agent opens its tab in front, and Chrome
activates the window for it, which raises the agent Chrome over the user's
work. It happened on 2026-11-17 with a Taobao link: the new page became the
selected tab. Once the page has asked for the tab, neither CDP nor the
extension can stop the activation; `chrome.tabs.onCreated` comes after it.

So `click_at_xy()`, `press_key()` and `scroll()` put one-shot `click` and
`submit` listeners on the page for the length of the input. A link, or a GET
form (its `target`, or the submit button's `formtarget`), that would open a new
browsing context and that no page handler has already taken
(`defaultPrevented`) is cancelled and opened by the helpers instead, a form as
its action URL with the fields as the query: a background tab from the
extension (`bhOpenTab`), navigated with the referrer a click would have sent
(`strict-origin-when-cross-origin`, none for `rel=noreferrer`), and grouped
with the session. The daemon stays on the page that was clicked, as it did
before, and the call prints the new tab's target id for `switch_tab()`.
Measured on Chrome 157, 2026-11-17, sampling the frontmost app every 0.1 s: a
click on the link, an Enter on it, a click on a GET form's submit button and an
Enter in its field each gave an inactive tab in the session's group with
`document.referrer` set, and the agent Chrome never came to the front. Without
the guard the form raised Chrome, as do `window.open()` from a click handler
and a popup window.

Left alone, so still in front: POST forms (`Page.navigate` cannot carry their
body), `window.open()`, whose caller may use the window it returns, and clicks
inside cross-origin iframes (the listeners are on the top page). Also left
alone: links with `rel=opener` or `download`, and targets naming a frame on the
page. `el.click()` from `js()` on such a link opens nothing at all: without a
user gesture the popup blocker takes it.

The same run checked what else a click can start: a file chooser,
`showOpenFilePicker()`, fullscreen, print, `alert()`, WebAuthn, notification
and location prompts, an external protocol, a download, picture-in-picture,
`window.focus()` and Cmd+N / Cmd+T key events. None brought the unfocused agent
Chrome to the front. `print()` and `alert()` do block the page, so later
`js()` calls time out until the dialog is gone.

## The tab lock

Every session's tabs live in one Chrome, and `switch_tab()`, `js(target_id=)`,
`close_tab()`, `activate_tab()` and `mark_tab()` take any target id. Nothing
stopped one session from driving, closing or marking another session's tab.

A tab belongs to the session whose tab group holds it. The extension already
keeps that record (`bhGroup`), so the lock needs no second one: `cdp()` in
`agent_helpers.py` checks the three CDP calls these helpers make with a target
id (`Target.attachToTarget`, `activateTarget`, `closeTarget`), and `mark_tab()`
checks its target, against the worker's `bhOwner`. Another session's tab is
refused with `tab_locked`, naming the group and the session, while that
session's daemon answers and it has not called `close_session()`. Ungrouped
tabs, the user's own, stay open to anyone, as before.

A tab changes hands one way: its session lets go of it. `close_session()` marks
the session done (`bhCloseSession`), which frees the tabs it keeps for the
user; a daemon that is gone (the session ended, the reaper stopped it) frees
them too. The next session that switches to such a tab takes it into its own
group, so its `close_session()` and the reaper now treat it as that session's;
opening a tab again makes the first session not done. There is no way to take a
tab from a running session and no override: an agent would reach for it at the
first refusal, and a second session rarely needs the tab itself, since logins
belong to the profile and a tab of its own has them.

**A closed tab is reported, not replaced.** When its tab closed, the daemon
used to attach to its own first tab or a new blank one and run the call there,
so a click meant for a closed tab landed on another page and returned
normally. Measured with the unpatched daemon, Chrome 157, 2026-11-19:
`close_tab()` then `click_at_xy(10, 10)` returned, and `current_tab()` was a new
`about:blank`. The fork now answers every page call and `current_tab()` with
`tab_gone` until the session moves to a tab with `new_tab()` or
`switch_tab()`; switching to a closed tab gives `tab_gone` too.

Measured on Chrome 157, 2026-11-19, two sessions (`cc-<id>` from the wrapper,
`sub-locktest` as a sub-agent's `BU_NAME`) on a second agent Chrome in the
background: B's `switch_tab`, `js(target_id=)`, `close_tab` and `mark_tab` on
A's tab each raised `tab_locked`; B kept working in its own tab; A's calls
after its tab closed raised `tab_gone` and `new_tab()` recovered; after A's
`close_session()` B took A's kept tab into its group, A was then refused, and A
took it back once B's daemon stopped. The check adds about 10 ms to a switch.

Not copied from agent-browser's `--pin-tab`: the lock is always on rather than
a flag, since anything that depends on an agent remembering a flag fails the
first time it forgets; it covers the session's whole group rather than one
pinned tab; and a `tab_gone` error carries no last URL for recovery.

## Element refs

Agents found elements in `Accessibility.getFullAXTree` and clicked by
coordinates, so a click on whatever covered the element (a cookie banner, a
dialog) or had taken its place after a re-render still returned normally.

`snapshot()` lists the page's interactive elements, those with an ARIA widget
role, one per line with a ref: `@e3 button "Sign in"`, plus a field's value
and `[disabled]`, `[checked]`, `[selected]` or `[expanded]`. `click(ref)` and
`fill_input(ref, text)` act on them. Each `browser-harness` call is its own
process, so the refs live in a file beside the daemon's log
(`bu-<name>.refs`, removed with it by the reaper), recording the tab, the
document (its loader id), the backend node id, role and name of each.

A ref keeps naming one element:

- Its node is used while it is in the same document and still has the role and
  name of the snapshot; a framework can reuse a node for other content. Node
  ids from another document are never used.
- Otherwise it is found again by role and name, and refused when that matches
  no element or several, or when the snapshot itself had several; a new
  snapshot is the answer. Refs are numbered once per session, so an old ref can
  never name a new element, and the same node keeps its ref across snapshots.
- Before the press, the element is scrolled into view and its centre is hit
  tested: hidden, zero-sized, disabled, outside the viewport or covered by
  another element (its label counts as the element) is an error and nothing is
  clicked. A one-shot `mousedown` listener then confirms the press reached the
  element; one that landed elsewhere (a dialog that opened in between) is an
  error too.

Measured on Chrome 157, 2026-11-19, on TodoMVC's React example in a background
tab: typing three items by ref, toggling one by ref, routing to `#/active` and
back, reloading and adding an item through a ref from before the reload all
worked; a ref to a removed checkbox (several unnamed checkboxes) was refused, a
link replaced by an identical node was found again, a link renamed in place was
refused, and a full-page overlay, a zero-sized link and a dialog that appeared
150 ms after the check each failed the click with the link not followed. A
snapshot of a long Wikipedia article was 745 lines, 24 k characters, 0.17 s.

Not copied from agent-browser's `snapshot`: the full tree with headings and
text (agents read text with `js()`), elements that are only clickable by
`cursor: pointer`, and iframes. Refs cover the top document's ARIA widgets;
anything else is still clicked by coordinates. Its wait for animation frames
before measuring is left out too: a background tab may not run them, and an
instant `scrollIntoView` is measured at once.

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

`open-browser-use reap` (`libexec/reap.py`) runs detached from the wrapper, at most every ten minutes. A
session has ended when its agent's own records say so:

| Name | Ended when |
|---|---|
| `cc-<id>` | no running `claude` process holds the session (`~/.claude/sessions/<pid>.json`) **and** its transcript is an hour old |
| `cx-<id>` | its Codex rollout file is a day old |
| anything else | the daemon started a day ago, or no daemon is left |

Claude Code needs both signals so neither alone can stop a live session. For an
ended session, unmarked tabs close at once and marked ones a day later. A
mistaken stop costs little: the session's next call starts a new daemon.

A session left open in a terminal never ends by these signals: on 2026-11-26 a
group last used 25 hours earlier was still open. So the reaper also calls
`close_session()` for a running session that has made no browser-harness call
for two hours: its unmarked tabs close, its marked tabs and its name stay, and
its daemon keeps running, so a later call gets `tab_gone` and opens a new tab
rather than acting on a blank page. The last call is the modification time of
the daemon's log, which `agent_helpers.py` touches when it loads; the daemon
writes there only when it starts or reattaches.

Closing a profile's last tab closes its window and unloads the profile, and its
next session can only open it again by bringing Chrome to the front
(docs/profiles.md). The reaper closes grouped tabs only, so before it does it
makes sure the profile has one tab outside every group, an empty one if need be;
that tab stays.

## Restarting the shared Chrome

Every session's tabs live in one Chrome, so restarting it closes work in
progress. It happened: a restart to load a new extension closed another
session's login page that the user was about to use. `open-browser-use restart`
now refuses while another session's daemon is alive, and only `--force`, after
the user agrees, goes ahead. Browser-wide settings count the same: turning off
tab sync once closed every session's groups, because Chrome removes
account-stored groups from the device when that data type is switched off.

## The fork

Three patches live on the `max` branch of
[max1874/browser-harness](https://github.com/max1874/browser-harness), each
because the helpers process cannot reach what it changes:

- The driven tab is marked with `<html data-browser-harness-agent>` instead of a
  🐴 prefix on `document.title`. Upstream's prefix changes the real page title,
  so anything that reads titles reads the horse too. The mark is set by the
  daemon process.
- A `release_target` daemon command: `mark_tab()` hands the tab over, so a
  daemon that stops no longer closes a tab the user was asked to look at.
- `tab_gone` instead of a replacement tab when a named daemon's tab has closed
  (above). Only the daemon knows which tab it was on: each helpers process
  starts after the move has already happened.

## Data collection

browser-harness enables telemetry by default, and its CLI events skip the
redaction its other events get: a packet capture against v0.1.9 (August 2026,
not rechecked since) showed the full script, its
stdout and every helper argument, verbatim, including a URL with a token in it.
`install.sh` turns telemetry and recordings off and stops the per-run version
check.
