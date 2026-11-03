# open-browser-use

Read README.md and docs/design.md before editing. This is a layer on
browser-harness, not a replacement: extend its own mechanisms (the
`agent_helpers.py` extension point, the `BU_NAME`/`BU_CDP_URL` variables) before
touching the fork, and keep fork patches to what the helpers process cannot reach.

- The user's screen is not ours. Nothing activates a tab or raises Chrome unless
  the user has to act there. A timeout or a hidden-tab quirk is not a reason to.
- The agent Chrome is shared by every session on the machine. Never quit it,
  kill another session's daemon or change a browser-wide setting (sync, account,
  profile, extensions) while another session is attached. Restart only through
  `bh-agent-chrome --restart`, which refuses in that case. Both rules exist
  because each was broken once and closed someone's tabs.
- Diagnose "did nothing" by whether the event happened, not by whether the state
  looks right. Background clicks were once misread as "landed but unfocused"
  from `document.activeElement`; a listener showed no `mousedown` at all.
- Test a load-time patch after restarting the daemon. A live daemon keeps the
  previous CDP session's settings, so a broken patch still passes.
- Check whether a skill is registered by a deterministic dump
  (`codex debug prompt-input`), never by asking a model which skills it has.
  `SKILL.md` must be a real file; a symlinked `SKILL.md` is skipped silently.
- When the worker's functions change, bump `self.bhApi` in
  `extension/bh_session_groups_sw.js` and `_GROUPS_API` in `agent_helpers.py`
  together.
- Prefer removing a hazard in code over adding a sentence to the skill. Count
  how often agents hit it first (docs/design.md and todo.md have the numbers).
- Keep README claims and what has actually been run in sync. Say which Chrome
  version and which date a measurement comes from.
- Nothing in this repository may come from another product's assets. The
  pointer and icon are drawn here.
