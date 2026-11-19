# Comparison with similar tools

Read against source, not only README. Update an entry when its project or ours changes a claim below.

## vercel-labs/agent-browser

[agent-browser](https://github.com/vercel-labs/agent-browser) (Vercel Labs, Rust, Apache-2.0, started 2026-01) is the closest project: a CLI that gives an agent a browser one command at a time, through a daemon speaking the Chrome DevTools Protocol. Read at commit `deda8ef` (2026-11-18), its tab binding and refs again at `25b5d76` (2026-11-19); it was not run.

| | agent-browser | open-browser-use |
| --- | --- | --- |
| Disturbance | Headless by default, so nothing appears. Headed starts the Chrome binary without `--no-startup-window`; in attach mode (`--cdp`, `--auto-connect`) new tabs are created in the foreground (`cli/src/native/cdp/types.rs:151-153`), every tab switch calls bring-to-front (`browser.rs:2276`), and input to a background tab needs `tab keep live` | Background launch with no window, background tabs from the extension, focus emulation on by default, new-tab links reopened in the background (`design.md`) |
| Logins | A fresh temporary profile per launch by default; `--profile <path>` persists one; `--profile <Name>` copies the user's everyday profile with the real keychain; `--auto-connect` drives the user's live Chrome | One persistent agent Chrome with its own profiles, picked per project folder; the everyday Chrome is never touched |
| Several agents | One daemon and browser per `--session`, default `"default"`; `--pin-tab` gives a strict tab lock (`tab_locked`, `tab_gone`) | Session name taken from the agent's session id; one tab group per session; `close_session`, `mark_tab` and a reaper; an always-on lock on each session's group (`tab_locked`, `tab_gone`) |
| Reading a page | `snapshot` with refs (`@e1`), stale-ref recovery by role and name, clicks fail on covered targets, waits for text, URL, JS and downloads | `snapshot()` of ARIA widgets with refs, stale-ref recovery by role and name, clicks fail on hidden or covered targets and when the press lands elsewhere; the raw accessibility tree and coordinate clicks for the rest; load, element and network-idle waits |
| Distribution | npm, Homebrew, `npx`; `install` fetches Chrome for Testing; `upgrade`; the CLI serves its own version-matched skill text; MCP server; macOS, Linux, Windows | `curl \| sh` into a release checkout, uv, a hand-loaded extension; macOS only |

**Decision (2026-11-18): keep building open-browser-use and borrow from agent-browser.** Building on its attach mode would fail the zero-activation bar in its own code (foreground tab creation, bring-to-front on switch, focus emulation opt-in), and its new tabs would open in Chrome's last-used profile, breaking per-folder profiles. Switching would lose persistent logins and the separation from the user's browser unless we run headless.

Worth borrowing: element refs with stale-ref recovery and a strict tab lock (both taken on 2026-11-19; design.md says what was left out), waits for text, URL and downloads, a domain allowlist and confirmation step for risky actions, and skill text served by the installed version.

Not established without a hands-on run: whether its foreground tabs actually raise Chrome on macOS when a window exists; whether clicks land on a pinned background tab without `tab keep live`; what a snapshot costs in tokens against our filtered reads; whether `--profile <Name>` triggers a Keychain dialog.
