---
name: open-browser-use
description: "Operate an interactive browser through browser-harness (the open-browser-use agent Chrome, or an authorized remote browser). Use for clicks, forms, logged-in pages, or rendered content; plain public-page retrieval needs no browser."
---

# open-browser-use

Direct control of a real Chrome over CDP, from Python heredocs passed to the
`browser-harness` command.

## When not to use

If a plain HTTP request can read it (a public page, an API, docs), use `curl` or
your fetch tool. Use the browser for interaction, logged-in sessions, JS-rendered
or bot-protected pages, or when a direct fetch returns an empty shell.

## The browser you are driving

- A dedicated **agent Chrome** on its own data directory and port 9333, shared by
  every agent session on this machine. Logins persist across sessions. The
  user's own browser is never involved.
- It can hold several Chrome profiles with different accounts (personal, work).
  Your session gets the one mapped to your project folder; its tabs open in that
  profile's windows.
- The `browser-harness` command already isolates you: it gives your session its
  own daemon, tabs and profile. Do not set `BU_NAME`, `BU_CDP_URL` or
  `OBU_PROFILE`.
- **Sub-agents** inherit your session id and would share your tab. When you
  delegate browser work, give each sub-agent its own name and tell it to prefix
  every call with it: `BU_NAME=sub-<task> browser-harness <<'PY'`.
- Never quit Chrome or kill another session's daemon. To restart Chrome, run
  `open-browser-use restart`; it refuses while another session is attached,
  and then you ask the user. Browser-wide settings (sync, account, profile,
  extensions) count the same: ask first.
- Do not edit `agent_helpers.py`: it is shared and versioned. Define what your
  task needs inside your heredoc.

## A session

```bash
browser-harness <<'PY'
name_session("🧾 Download May invoices")  # once: 2–6 words in the user's language, an emoji picked for this task
new_tab("https://example.com")             # first navigation; later ones use goto_url()
wait_for_load()
print(page_info())
PY
```

- Helpers are pre-imported; the daemon keeps your tab between calls, so do not
  call `new_tab()` in every script.
- Tabs opened with `new_tab()` join your session's tab group.
- A tab the user must act in (log in, enter a code, approve): `mark_tab("handoff")`.
  It is kept open and brought to the front. Never call `activate_tab()` yourself.
- A tab holding a result for the user: `mark_tab("deliverable")`, and name it in
  your reply; the mark is invisible.
- When the browser work is done: `close_session()`. It closes your tabs except
  the marked ones. Skip it while waiting on the user in a handoff tab.
- Tabs in another running session's group are locked: `switch_tab()`,
  `js(target_id=)`, `close_tab()` and `mark_tab()` on them raise `tab_locked`.
  Open your own with `new_tab()`; logins belong to the profile, not the tab. A
  tab is free once its session has called `close_session()` or ended, and
  switching to it makes it yours.
- `tab_gone` means your tab was closed (by you, `close_session()`, the user, or
  because you made no browser call for two hours, which closes your unmarked
  tabs): `new_tab()` or `switch_tab()` to one of yours.

## Helpers

```text
new_tab(url) -> target_id      goto_url(url)            page_info()
wait_for_load(timeout=15)      wait_for_element(selector, timeout=10, visible=False)
wait_for_network_idle(timeout=10, idle_ms=500)          wait(seconds)
js(expression, target_id=None)                          cdp("Domain.method", **params)
click_at_xy(x, y, button="left", clicks=1)              scroll(x, y, dy=-300, dx=0)
type_text(text)                fill_input(selector, text, clear_first=True)
press_key(key, modifiers=0)    dispatch_key(selector, key="Enter")
upload_file(selector, path)    capture_screenshot(path=None, full=False, max_dim=None)
list_tabs()  current_tab()  switch_tab(target)  close_tab(target=None)  ensure_real_tab()
iframe_target(url_substr)      http_get(url, headers=None)
name_session(title)  mark_tab("handoff" | "deliverable" | None, target=None)  close_session()
snapshot() -> str              click("@e3")             fill_input("@e5", text)
```

Nothing else exists: there is no `screenshot`, `goto` or `navigate`.

## Working a page

- **Wait for a condition, not a duration.** After a navigation `wait_for_load()`;
  for content an app renders later `wait_for_element(selector)`; after a submit
  `wait_for_network_idle()`. A fixed `time.sleep()` longer than a second is
  almost always one of these.
- **Act through refs.** `snapshot()` lists the page's buttons, links, fields
  and other controls as `@e3 button "Sign in"`; a long page has hundreds, so
  filter before printing:
  `print("\n".join(l for l in snapshot().splitlines() if "Sign" in l))`.
  Then `click("@e3")` or `fill_input("@e5", "text")`. They raise instead of
  acting when the element is hidden, disabled or covered (a banner, a dialog:
  deal with it first), or when the page changed and the ref no longer names one
  element: take a new `snapshot()`. Do not fall back to its coordinates.
- **Elements a snapshot lacks** (a clickable `div` without a role, content in
  an iframe): `cdp("Accessibility.getFullAXTree")["nodes"]` gives role, name
  and `backendDOMNodeId`; filter in Python. Centre:
  `q = cdp("DOM.getBoxModel", backendNodeId=n)["model"]["content"]; x, y = sum(q[0::2])/4, sum(q[1::2])/4`,
  then `click_at_xy(x, y)`, which passes through iframes and shadow DOM.
  Negative or oversized coordinates mean scroll first. Verify with a targeted
  `js(...)` or `page_info()`.
- **`js()`**: write the expression as a raw string (`r"""…"""`) whenever it holds
  a regex or a backslash, or Python eats the escapes. Check a selector's result
  for `null` before reading from it.
- **Screenshots** when layout or imagery matters: `capture_screenshot(path, max_dim=1800)`
  keeps a 2× screen under the 2000 px limit image-aware models enforce.
- **Print little.** Slice text and filter lists before printing; long output
  costs context on every later turn.
- **Login walls:** use SSO when Chrome is already signed in; otherwise hand off
  (`mark_tab("handoff")`) and stop. Never type passwords, MFA codes or consent.

For a specific mechanic (dialogs, downloads, uploads, iframes, shadow DOM,
dropdowns, drag and drop, cookies, network requests, PDFs, scrolling, tabs,
viewport), read the matching file in `interaction-skills/` next to this one.

## When it does not connect

Run `browser-harness --doctor`. If Chrome cannot be launched (Codex's sandbox
blocks it), ask the user to run `open-browser-use start` once in a normal terminal;
after that you connect normally.
