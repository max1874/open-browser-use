# open-browser-use

Open Browser Use lets several coding agents share one real, logged-in browser on
your Mac at the same time, in the background, without ever taking your screen.

It is a thin layer on top of [browser-use/browser-harness](https://github.com/browser-use/browser-harness).
browser-harness gives an agent direct control of Chrome over the DevTools
Protocol. This repository makes that safe to leave running all day for Claude
Code, Codex and their sub-agents:

| Problem | What happens here |
|---|---|
| Agents drive the tab you are reading | One dedicated Chrome on its own profile and port; your everyday browser is never touched |
| Two sessions fight over one tab | Each agent session gets its own daemon and its own tabs, derived from the session id, with no flag to remember |
| Background clicks silently do nothing | Focus emulation turns a hidden tab's input back on, so clicks and key presses land without raising Chrome |
| You cannot tell whose tabs are whose | Every session's tabs share one named, coloured tab group: `🔑 Sign up for Tiingo` |
| You cannot see what the agent is doing | A glowing pointer glides to each click before it lands |
| Ended sessions leave tabs and processes behind | A reaper reads the agents' own session records and closes what belongs to sessions that have ended |

> Status: early. This is the public home of a setup that has run daily on one
> Mac since August 2026, on Google Chrome. The packaging in this repository has
> not yet been installed from scratch on another machine. See [todo.md](todo.md).

## How it fits together

```text
agent (Claude Code / Codex)
  │  browser-harness <<'PY' … PY
  ▼
bin/browser-harness            wrapper with the upstream name, so every doc and example still works
  ├─ BU_NAME = cc-<session> / cx-<thread>       one daemon + one set of tabs per session
  ├─ BU_CDP_URL = 127.0.0.1:9333                bin/bh-agent-chrome starts the agent Chrome if needed
  └─ every 10 min, detached: bin/bh-reap        stop ended sessions' daemons, close their groups
  ▼
browser-harness daemon ──CDP──► agent Chrome (own profile, own port)
  │                                 └─ extension/  tab groups, pointer, tab marks
  ▼
agent_helpers.py               loaded by browser-harness's own extension point:
                               focus emulation, new_tab() grouping, name_session(),
                               mark_tab(), close_session(), pointer glide
```

## Install

Requires macOS, [uv](https://docs.astral.sh/uv/) and Google Chrome.

```bash
git clone https://github.com/max1874/open-browser-use.git
open-browser-use/install.sh
```

`install.sh` is idempotent. It installs browser-harness as a uv tool, links the
wrapper and the helpers into place, turns browser-harness's data collection off,
and copies the skill into `~/.claude/skills` and `~/.codex/skills` when they
exist. The agent Chrome starts on the first browser call.

The agent Chrome is a separate profile, so it starts logged out. To sign in to a
site once, for every later session:

```bash
open -a "Google Chrome" --args --user-data-dir="$HOME/.local/share/agent-chrome"
```

## What the agent calls

Everything browser-harness offers, plus:

```python
name_session("🧾 Download invoices")   # once, when browser work starts: names the tab group
new_tab("https://example.com")          # grouped under this session automatically
click_at_xy(x, y)                       # the pointer glides there first (BH_CURSOR=0 to turn off)
mark_tab("handoff")                     # the user has to act here: keep it open
mark_tab("deliverable")                 # a result the user should look at: keep it open
close_session()                         # close this session's tabs, except the marked ones
```

The skill in [skill/browser-harness/SKILL.md](skill/browser-harness/SKILL.md)
tells agents when to call each of these.

## Known limits

- **Chromium only.** Everything here and in browser-harness speaks the Chrome
  DevTools Protocol, and the tab groups use `chrome.tabGroups`. Firefox dropped
  CDP; Safari never had it. `BH_AGENT_CHROME_APP` can name Edge, Brave or
  Chromium, but only Google Chrome has been tested.
- **macOS only.** The launcher uses `open -g` to start Chrome without raising it.
- **Codex's sandbox cannot launch Chrome.** It blocks LaunchServices, so `open`
  fails inside it. Start the agent Chrome once from a normal terminal
  (`bh-agent-chrome`); after that Codex connects normally.
- **Sub-agents share their parent's session id**, so they share its tabs. Give
  each browser sub-agent its own `BU_NAME`.
- **Only tabs opened with `new_tab()` are grouped.** A tab a page opens by
  itself stays wherever Chrome puts it.

## Credits

Built on [browser-use/browser-harness](https://github.com/browser-use/browser-harness)
by Browser Use, through a fork with two small daemon patches
([max1874/browser-harness](https://github.com/max1874/browser-harness), branch `max`).
The skill started from browser-harness's own `SKILL.md`.

MIT licensed; see [LICENSE](LICENSE).
