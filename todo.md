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

## Known gaps, no plan

- **Chromium browsers other than Google Chrome.** `OBU_CHROME_APP` exists;
  none has been tried.
- **Tabs a page opens by itself** are not grouped, so `close_session()` does not
  see them.
- **Extensions that talk to a desktop app** (1Password, Codex) reach it through
  a native messaging host, whose manifest apps register only in the everyday
  Chrome's folder; in the agent Chrome they cannot connect until the manifest
  is linked into its `NativeMessagingHosts/`. The author's setup does that by
  hand; it is a general problem and may belong in `install.sh`.
- **Sub-agents** inherit their parent's session id and share its tabs. Telling
  them apart needs an id the agent host does not export.
