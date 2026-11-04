# Not done

README's "Known limits" says what this cannot do today. This file says what is
meant to move and what each item is blocked on. Nothing here is scheduled.

## Before the repository goes public

**README screenshots.** `install.sh` on a clean account of a second Mac
(Chrome 156, 2026-11-04) gave grouped tabs, a drawn pointer and trusted
background clicks, read from the extension and the page. The tab groups as the
user sees them were not captured: `screencapture` over ssh has no display.
Done when a screenshot of each is in the README.

**A demo.** open-computer-use leads with a recording; this needs one too:
two agent sessions working in their own named groups while the user keeps
typing in another app.

**An extension icon.** The manifest has none, so Chrome shows its default
puzzle piece. The previous icon was not ours to publish.

**A Chrome Web Store listing, last.** Releases carry the extension as a zip
(`scripts/release.sh`). The store gives one-click install but reviews every
change, and the publisher account showed "2 published, limit 2" on 2026-11-02;
check that limit first.

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
