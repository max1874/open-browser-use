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

Switched on the author's Mac on 2026-11-05: the commands, helpers and skill
come from this repository. Still open, all needing an unlocked screen:

- "Load unpacked" `extension/` in the running agent Chrome (the picker cannot
  be scripted, docs/design.md), then delete the predecessor's CDP-loaded copy
  (`dogdonim…`, identical worker), and confirm `bh-agent-chrome`'s Secure
  Preferences check finds the new one.
- Then hand the launchd keeper to its new home (a personal repository) with its
  `install.sh`. Until then the old keeper still cold-starts Chrome with the
  predecessor's launcher, which loads the old extension: the safe fallback.
- Then archive the predecessor.

## Known gaps, no plan

- **Chromium browsers other than Google Chrome.** `BH_AGENT_CHROME_APP` exists;
  none has been tried.
- **Tabs a page opens by itself** are not grouped, so `close_session()` does not
  see them.
- **Sub-agents** inherit their parent's session id and share its tabs. Telling
  them apart needs an id the agent host does not export.
