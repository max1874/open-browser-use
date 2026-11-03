# Not done

README's "Known limits" says what this cannot do today. This file says what is
meant to move and what each item is blocked on. Nothing here is scheduled.

## Before the repository goes public

**Install from scratch and run it.** Everything here ran daily on one Mac
through a private predecessor, but this copy differs from it: the pointer is a
new drawing, the extension moved from `session-groups/` to `extension/` (which
also changes its id), and the machine-specific parts were removed. None of that
has run. Done when `install.sh` on a clean user account gives grouped tabs, a
visible pointer and trusted background clicks (the click check in
docs/design.md), and a screenshot of each goes into the README.

**A demo.** open-computer-use leads with a recording; this needs one too:
two agent sessions working in their own named groups while the user keeps
typing in another app.

**An extension icon.** The manifest has none, so Chrome shows its default
puzzle piece. The previous icon was not ours to publish.

**Polish the skill.** Measured over 95 Claude Code sessions (October 2026):
- `js()` failed 129 times in 8 sessions on `Identifier 'x' has already been
  declared` (top-level `const` persists between calls). Fix in the helper:
  retry inside its own scope.
- `capture_screenshot(path)` failed 36 times in 10 sessions because the
  directory did not exist. Fix in the helper: create it.
- 7,683 fixed `time.sleep` calls, about 8.5 hours in total; `wait_for_element`
  and `wait_for_network_idle` were used in 0 sessions. The skill never
  mentions them. List the real helpers in the skill.
- `activate_tab()` was called in 14 sessions against the skill's rule, nearly
  always to show the user a handoff tab. `mark_tab("handoff")` should bring the
  tab forward itself.
- Agents guessed helpers that do not exist (`screenshot`, `goto`, `navigate`).
- The skill still carries upstream sections that do not apply here: cloud
  browsers, recordings, domain skills, the remote-debugging approval prompt.

## Moving off the private predecessor

The setup this came from lives in a private repository that is to be archived
once this one works. Before that:

- Switch the live install over (`install.sh` from here), then reload the
  extension from its new path.
- Decide where the machine-specific parts go: a launchd keeper that keeps the
  agent Chrome running, native-messaging-host links for extensions that talk to
  a desktop app, and bookmark and favicon syncing for a launcher. Of these, the
  native-host links are a general problem (any such extension cannot reach its
  app from a separate profile) and may belong here.

## Known gaps, no plan

- **Chromium browsers other than Google Chrome.** `BH_AGENT_CHROME_APP` exists;
  whether Edge, Brave or Chromium honour `--load-extension` (which would make the
  `loadUnpacked` workaround unnecessary there) is untested.
- **Tabs a page opens by itself** are not grouped, so `close_session()` does not
  see them.
- **Sub-agents** inherit their parent's session id and share its tabs. Telling
  them apart needs an id the agent host does not export.
