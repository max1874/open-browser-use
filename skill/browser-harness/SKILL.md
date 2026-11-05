---
name: browser-harness
description: "Operate an interactive browser through browser-harness using local Chrome/CDP or an authorized remote browser. Use for clicks, forms, logged-in pages, or rendered content; plain public-page retrieval needs no browser."
---

# browser-harness

Direct control of a real Chrome over CDP, from Python heredocs.

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
```

Nothing else exists: there is no `screenshot`, `goto` or `navigate`.

## Working a page

- **Wait for a condition, not a duration.** After a navigation `wait_for_load()`;
  for content an app renders later `wait_for_element(selector)`; after a submit
  `wait_for_network_idle()`. A fixed `time.sleep()` longer than a second is
  almost always one of these.
- **Find elements in the accessibility tree**, not in screenshots:
  `cdp("Accessibility.getFullAXTree")["nodes"]` gives every element's role, name
  and `backendDOMNodeId`. Filter in Python before printing; it is thousands of
  nodes. Centre for clicking:
  `q = cdp("DOM.getBoxModel", backendNodeId=n)["model"]["content"]; x, y = sum(q[0::2])/4, sum(q[1::2])/4`.
  Negative or oversized coordinates mean scroll first.
- **Click by coordinates**: `click_at_xy(x, y)` passes through iframes and shadow
  DOM. Then verify with a targeted `js(...)` or `page_info()`.
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
