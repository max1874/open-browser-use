# Profiles: personal and work logins in one Chrome

## The need

One person works on personal and company projects at the same time. Both sides
use the same services under different accounts: Cloudflare, cloud consoles
(Alibaba Cloud on one side, GCP on the other). An agent on a personal project
must find the personal logins and an agent on a company project the company
ones, simultaneously, without anyone switching accounts. One Chrome, one Dock
icon.

## Setup

1. In the agent Chrome, add a profile from the profile menu and name it, say
   "Work". A theme colour makes its windows recognisable at a glance.
2. In that profile, install the extension (chrome://extensions → Developer mode
   → Load unpacked → `extension/`), sign in to the sites, and add any other
   extensions it needs (1Password).
3. Write `~/.config/open-browser-use/profiles.json`, with the names exactly as
   the profile menu shows them:

```json
{
  "default": "Personal",
  "folders": { "~/Projects/Company": "Work" }
}
```

A session uses the profile of the deepest folder that contains its working
directory, otherwise `default`. Without the file there are no profiles: every
session uses whichever profile has the extension, as before.

## What Chrome actually does

Measured on Google Chrome 156 (macOS 26.4, a second Mac), 2026-11-03 to 11-05,
with one agent Chrome (one `--user-data-dir`, one CDP port) holding two profiles:

| # | Question | Result |
|---|---|---|
| 1 | Does one CDP port see every profile's tabs? | Yes. Each tab carries a `browserContextId`, one per profile |
| 2 | Can `Target.createTarget` open a tab in a chosen profile? | Only in the "default" context, which is the most recently active profile. Any other profile's id fails: `Failed to find browser context` |
| 3 | Can the daemon drive a tab of another profile? | Yes: `switch_tab()`, `js()`, focus emulation all work |
| 4 | Are logins separate? | Yes: a cookie set on example.com in one profile is absent in the other |
| 5 | Is the extension per profile? | Yes, each profile runs its own service worker, told apart by `browserContextId` |
| 6 | Can the extension open a tab in its own profile without raising Chrome? | Yes: `chrome.tabs.create({active: false})` from that profile's worker; Finder stayed frontmost |
| 7 | Can a profile window be opened without raising Chrome? | No. Both the Chrome binary and `open -g -n … --profile-directory=X` raised Chrome over Finder, and a URL passed along is ignored (a New Tab Page opens) |
| 8 | Can a cold start open several profiles? | No. Without `--profile-directory` Chrome shows the profile picker, or with the picker turned off opens one profile or none, whatever Local State lists as last active and with session restore on |
| 9 | Does an idle worker stay reachable? | Not by itself: it stops after 30 s. One that calls an extension API every 20 s was still running after 77 s; one without was gone |

## How it works

**Which profile** (`bin/browser-harness`): the wrapper reads `profiles.json`
and exports `OBU_PROFILE`, the same way it derives `BU_NAME`, so agents never
pass it. Sub-agents inherit it.

**Cold start** (`open-browser-use start`): Chrome opens one profile (8), so it
opens the calling session's; Local State maps the name to its directory.
Preferences and the extension check cover every profile.

**Finding the profile's worker** (`agent_helpers.py`): every worker keeps
itself running (9) and stores the name of its profile. Chrome tells an
extension nothing about its profile, so the name is given from outside: when no
worker has the session's profile name, the helpers open a window of that
profile (`open-browser-use window Work`), take the context of the tab that
appears, and name that context's worker. The window's tab is the next one it
hands out. This raises Chrome (7), once per profile after a Chrome start or
after all of a profile's windows were closed; a profile with a window open
costs nothing. If that profile has no worker, the helpers raise an error that
says how to install the extension there, rather than use another profile's
logins.

**Opening a tab** (`new_tab`): CDP opens tabs only in the last used profile (2),
so the tab comes from the worker: `bhOpenTab()` opens it in the background in
the profile's last focused window, or in a new unfocused window. The daemon's
own blank tab is reused when it is in the right profile and closed when it is
not. Everything after that is unchanged.

**Groups, marks, `close_session()`, the reaper**: per worker, as before; the
reaper walks every profile's worker.

## Getting the extension into every profile

| Option | How | Cost |
|---|---|---|
| A. Chrome Web Store, unlisted | Install once per profile; it persists, updates itself, and syncs to a profile signed in to Google. Open-source users get one-click install | A review for every extension change (a same-day approval was observed on 2026-11-02). The publisher account exists, but its console read "2 published, limit 2" on 2026-11-02 and a third item is untried. `debugger` is a permission reviewers look at closely |
| B. Developer mode, "Load unpacked", once per profile (**chosen**) | Persists across restarts with no flag (Chrome 156, 2026-11-04: installed `UNPACKED`, worker running after a normal quit and relaunch, no warning shown) | One manual step per profile; tied to the folder it was loaded from |
| C. Load over CDP at every cold start | Open each profile in turn, load into each while it is the default | Chrome takes the screen once per extra profile at every cold start (7), and a CDP-loaded extension is also gone when its profile's last window closes |

## Rejected

- **Two Chrome instances** (two profiles directories, two ports). Everything is
  supported and nothing above is needed, but it is two Chrome apps in the Dock
  and twice the memory, which is what this design is meant to avoid.
- **CDP browser contexts** (`Target.createBrowserContext`): isolated and in one
  process, but kept in memory only, so every login is lost on restart.
- **Several accounts in one profile**: services differ in how well they support
  it, and two agents would still contend for the active account.
