# Profiles: personal and work logins in one Chrome (design, not built)

## The need

One person works on personal and company projects at the same time. Both sides
use the same services under different accounts: Cloudflare, cloud consoles
(Alibaba Cloud on one side, GCP on the other). An agent on a personal project
must find the personal logins and an agent on a company project the company
ones, simultaneously, without anyone switching accounts. One Chrome, one Dock
icon.

## What Chrome actually does

Measured on Google Chrome 156 (macOS 26.4, a second Mac), 2026-11-03, with one
agent Chrome (one `--user-data-dir`, one CDP port) holding two profiles:

| # | Question | Result |
|---|---|---|
| 1 | Does one CDP port see every profile's tabs? | Yes. Each tab carries a `browserContextId`, one per profile |
| 2 | Can `Target.createTarget` open a tab in a chosen profile? | Only in the "default" context, which is the most recently active profile. Any other profile's id fails: `Failed to find browser context` |
| 3 | Can the daemon drive a tab of another profile? | Yes: `switch_tab()`, `js()`, focus emulation all work |
| 4 | Are logins separate? | Yes: a cookie set on example.com in one profile is absent in the other |
| 5 | Is the extension per profile? | Yes, each profile runs its own service worker, told apart by `browserContextId`. `Extensions.loadUnpacked` takes no profile; it installs into the default one |
| 6 | Can the extension open a tab in its own profile without raising Chrome? | Yes: `chrome.tabs.create({active: false})` from that profile's worker; Finder stayed frontmost |
| 7 | Can a profile window be opened without raising Chrome? | No. Both the Chrome binary and `open -g -n … --profile-directory=X` raised Chrome over Finder |
| 8 | Does a CDP-loaded extension survive a restart if Chrome is relaunched with `--enable-unsafe-extension-debugging`? | No, in either profile. And only the profile named by `--profile-directory` reopened |

So everything except opening a tab works across profiles through the one
connection we already have, and opening a tab works through the extension of
that profile (6). The hard part is getting the extension into every profile
(5, 7, 8).

## Design

**Configuration**, `~/.config/open-browser-use/profiles.json`:

```json
{
  "default": "personal",
  "profiles": {
    "personal": { "dir": "Default" },
    "work":     { "dir": "Profile 1", "paths": ["~/Projects/About-Intelligence"] }
  }
}
```

**Which profile a session uses**: the first profile whose `paths` contains the
working directory, otherwise `default`; `BH_PROFILE=work` overrides. The wrapper
resolves it once and exports `BH_PROFILE`, the same way it derives `BU_NAME`, so
agents never pass it. Sub-agents inherit the working directory and therefore the
profile.

**Opening a tab** (`new_tab`): find our extension's worker whose
`browserContextId` belongs to the session's profile, call `bhOpenTab(url)` there
(`chrome.tabs.create({active: false})`, or `chrome.windows.create({focused:
false})` when the profile has no window), map the tab to its CDP target with
`chrome.debugger.getTargets()` (already how grouping works), then
`switch_tab()` to it and group it. Everything after that is unchanged.

**Telling the workers apart**: each worker stores its profile name in its own
`chrome.storage.local` when the extension is set up in that profile.

**Groups, marks, `close_session()`, `bh-reap`**: unchanged per worker; anything
that walks sessions walks every profile's worker.

**Cold start**: every configured profile must be open, so the launcher opens
each one and writes each one's preferences (vertical tabs, hidden saved-groups
bar).

**What the user does once per profile**: sign in to the sites, and install any
extensions that profile needs (1Password, Codex). Giving each profile a theme
colour and name makes its windows recognisable at a glance.

## The open choice: getting the extension into every profile

| Option | How | Cost |
|---|---|---|
| A. Chrome Web Store, unlisted | Install once per profile; it persists, updates itself, and syncs to a profile signed in to Google. The unsafe flag and CDP loading go away; open-source users get one-click install | A review for every extension change (a same-day approval was observed on 2026-11-02). The publisher account exists, but its console read "2 published, limit 2" on 2026-11-02 and a third item is untried. `debugger` is a permission reviewers look at closely |
| B. Developer mode, "Load unpacked", once per profile (**chosen**) | Persists across restarts with no flag (Chrome 156, 2026-11-04: installed `UNPACKED`, worker running after a normal quit and relaunch, no warning shown). The unsafe flag and CDP loading are gone | One manual step per profile; tied to the folder it was loaded from |
| C. Keep loading over CDP at every cold start | Open each profile in turn, load into each while it is the default | Chrome takes the screen once per extra profile at every cold start (7) |

## Rejected

- **Two Chrome instances** (two profiles directories, two ports). Everything is
  supported and nothing above is needed, but it is two Chrome apps in the Dock
  and twice the memory, which is what this design is meant to avoid.
- **CDP browser contexts** (`Target.createBrowserContext`): isolated and in one
  process, but kept in memory only, so every login is lost on restart.
- **Several accounts in one profile**: services differ in how well they support
  it, and two agents would still contend for the active account.
