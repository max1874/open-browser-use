"""Local agent helpers (not upstream — loaded by helpers._load_agent_helpers).

Managed by: the open-browser-use repo (docs/design.md); linked in by install.sh

Problem this solves
-------------------
CDP input (Input.dispatchMouseEvent / Input.dispatchKeyEvent) silently does
nothing when the target tab is not the selected tab in its Chrome window, or
when its window is occluded. Clicks fire no events at all; key presses are
dropped. Only Input.insertText and Runtime.evaluate keep working.

`Emulation.setFocusEmulationEnabled` flips the page's visibilityState to
"visible" for that CDP session and restores trusted mouse and key events —
without activating the tab, so Chrome is never raised to the macOS
foreground.

Verified 2026-08-24 on Chrome 151:
  hidden tab, no emulation → click events [] , press_key ''
  hidden tab, emulation on → click ["trusted=true"] , press_key 'Q'

The flag is per CDP session, so it is re-armed whenever the daemon attaches to
a different target (new_tab / switch_tab / ensure_real_tab), and before the
agent's input when the page reads hidden (the daemon also re-attaches silently).

Session tab groups
------------------
new_tab() also puts the tab into a tab group per agent session (BU_NAME),
titled "Claude · <cwd basename>" (or Codex) until the agent calls
name_session("🔑 Sign up for Tiingo") (emoji picked per task), the way Codex names its groups. CDP has no
tab-group API, so this calls the session-groups extension's service worker
over CDP. Purely cosmetic: any failure leaves the tab ungrouped and never
breaks the caller.

Codex-style cursor and tab status
---------------------------------
click_at_xy() and scroll() first glide a glowing pointer (drawn by the same
extension) to the target and wait for it to arrive, so a person watching sees
where the agent acts. capture_screenshot() hides it for the shot.
OBU_CURSOR=0 turns the cursor off. mark_tab() marks a tab as "deliverable" or
"handoff"; close_session() closes the session's tabs when its browser work is
done, keeping the marked ones.

Tab lock and element refs
-------------------------
A tab in another running session's group is refused (tab_locked) by every
call that takes a tab. snapshot() lists the page's interactive elements with
refs ("@e3") for click() and fill_input(), which re-find a re-rendered element
by role and name and refuse rather than act on another one (docs/design.md).
"""

import collections
import functools
import json
import os
import subprocess
import time

import browser_harness.helpers as _bh
from browser_harness import _ipc

_orig_cdp = _bh.cdp
_armed = False


def _arm_focus_emulation():
    """Enable focus emulation once for the daemon's current CDP session."""
    global _armed
    _armed = True  # set before the call: it re-enters cdp() below
    try:
        _orig_cdp("Emulation.setFocusEmulationEnabled", enabled=True)
    except Exception:
        _armed = False  # daemon not ready yet — retry on the next call


def cdp(method, session_id=None, **params):
    """Raw CDP, with focus emulation armed lazily on first use."""
    if method in _TAB_CALLS:
        _claim(params.get("targetId"))
    if not _armed:
        _arm_focus_emulation()
    return _orig_cdp(method, session_id=session_id, **params)


def _rearm_after(fn):
    """Attaching to another target starts a new CDP session — re-arm."""

    def wrapper(*args, **kwargs):
        global _armed
        try:
            return fn(*args, **kwargs)
        finally:
            _armed = False

    wrapper.__name__ = getattr(fn, "__name__", "wrapper")
    wrapper.__doc__ = getattr(fn, "__doc__", None)
    return wrapper


for _name in ("new_tab", "switch_tab", "ensure_real_tab"):
    _fn = getattr(_bh, _name, None)
    if _fn is not None:
        globals()[_name] = _rearm_after(_fn)
del _name, _fn


_GROUPS_SW = "/bh_session_groups_sw.js"
_GROUPS_API = 11  # must match self.bhApi in extension/bh_session_groups_sw.js
_PROFILE = os.environ.get("OBU_PROFILE")  # set by bin/browser-harness from profiles.json
_OBU = os.path.join(os.path.dirname(os.path.realpath(__file__)), "bin", "open-browser-use")


def _session_key():
    return os.environ.get("BU_NAME") or "default"


# The daemon log's modification time is when this session last ran
# browser-harness: libexec/reap.py closes the tabs of one that has not for two
# hours. The daemon itself writes there only when it starts or reattaches.
_ipc.log_path(_session_key()).touch()


def _find_groups_workers():
    infos = _orig_cdp("Target.getTargets")["targetInfos"]
    return [t for t in infos if t["type"] == "service_worker" and t["url"].endswith(_GROUPS_SW)]


def _wait_groups_workers(wake):
    """Our extension's workers, one per Chrome profile that has it. They keep
    themselves running; wake=True still opens (and closes) a background
    about:blank when there is none, which wakes a worker from before that."""
    workers = _find_groups_workers()
    if workers or not wake:
        return workers
    waker = _orig_cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    try:
        for _ in range(20):  # give it ~2s
            time.sleep(0.1)
            if workers := _find_groups_workers():
                return workers
        return []
    finally:
        _orig_cdp("Target.closeTarget", targetId=waker)


def _eval_in(sw, expr):
    sid = _orig_cdp("Target.attachToTarget", targetId=sw["targetId"], flatten=True)["sessionId"]
    try:
        r = _orig_cdp("Runtime.evaluate", session_id=sid, expression=expr,
                      awaitPromise=True, returnByValue=True)
        return r.get("result", {}).get("value")
    finally:
        _orig_cdp("Target.detachFromTarget", sessionId=sid)


def _current(sw):
    """sw itself, or after reloading a stale worker script, its replacement; None if that fails."""
    if _eval_in(sw, "self.bhApi") == _GROUPS_API:
        return sw
    # A reload clears storage.session, i.e. every session's tab status (tab
    # ids survive it), so carry them across.
    status = _eval_in(sw, "chrome.storage.session.get('status').then(r => r.status || {})") or {}
    try:
        _eval_in(sw, "chrome.runtime.reload()")
    except Exception:
        pass  # the reload tears down the session it was sent on
    for _ in range(30):
        time.sleep(0.1)
        fresh = next((w for w in _find_groups_workers() if w["browserContextId"] == sw["browserContextId"]), None)
        if fresh and _eval_in(fresh, "self.bhApi") == _GROUPS_API:
            if status:
                _eval_in(fresh, f"chrome.storage.session.set({{status: {json.dumps(status)}}})")
            return fresh
    return None


def _open_profile():
    """Open a window of this session's Chrome profile, which also starts it, and
    name its worker, which hands out the window's tab next. Chrome comes to the
    front: no way to open a profile in the background was found (docs/profiles.md).

    The window is recognised by its New Tab Page: tabs that sessions open are
    about:blank, and naming the wrong profile's worker would stick."""
    before = {t["targetId"] for t in _orig_cdp("Target.getTargets")["targetInfos"]}
    r = subprocess.run([_OBU, "window", _PROFILE], capture_output=True, text=True)
    if r.returncode:  # e.g. no such profile, or it lacks the extension: says how to fix it
        raise RuntimeError(r.stderr.strip())
    for _ in range(100):
        time.sleep(0.1)
        infos = _orig_cdp("Target.getTargets")["targetInfos"]
        tab = next((t for t in infos if t["type"] == "page" and t["targetId"] not in before
                    and t["url"].startswith(("chrome://newtab", "chrome://new-tab-page"))), None)
        sw = tab and next((t for t in infos if t["type"] == "service_worker" and t["url"].endswith(_GROUPS_SW)
                           and t["browserContextId"] == tab["browserContextId"]), None)
        if sw:
            sw = _current(sw)
            if sw:
                _eval_in(sw, f"bhSetProfile({json.dumps(_PROFILE)}, {json.dumps(tab['targetId'])})")
                return sw
            break
    raise RuntimeError(f'the Open Browser Use extension did not start in the Chrome profile "{_PROFILE}"')


def _groups_worker(wake=False, open_profile=False):
    """The extension's worker in this session's profile; None if there is none."""
    for sw in _wait_groups_workers(wake):
        try:  # a worker can go away under us, e.g. with its profile's last window
            sw = _current(sw)
            if sw and (not _PROFILE or (_eval_in(sw, "bhProfile()") or "").lower() == _PROFILE.lower()):
                return sw
        except Exception:
            continue
    return _open_profile() if _PROFILE and open_profile else None


def _call_groups_worker(fn, *args, wake=False, open_profile=False, sw=None):
    """Call fn(*args) in this session's extension worker; None if there is none."""
    sw = sw or _groups_worker(wake, open_profile)
    if not sw:
        return None
    return _eval_in(sw, f"{fn}({', '.join(json.dumps(a) for a in args)})")


def _group_tab(target_id, sw=None):
    """Put the tab into this session's group via the extension."""
    try:
        key = _session_key()
        agent = {"cc": "Claude", "cx": "Codex"}.get(key.split("-")[0], key)
        default_title = f"{agent} · {os.path.basename(os.getcwd()) or '/'}"
        _call_groups_worker("bhGroup", target_id, key, default_title, sw=sw)
    except Exception:
        pass


def name_session(title):
    """Name this session's tab group, Codex style: emoji picked for the task + a short task name, e.g. "🔑 Sign up for Tiingo".

    Call it once when browser work starts (before or after the first new_tab()).
    The name sticks to the session, so a group recreated later gets it back.
    Returns False if the session-groups extension is not loaded.
    """
    try:
        return _call_groups_worker("bhNameSession", _session_key(), str(title), wake=True, open_profile=True) is not None
    except Exception:
        return False


# --- Tab lock ------------------------------------------------------------------

# Every session's tabs are in one Chrome, and switch_tab(), js(target_id=),
# activate_tab() and close_tab() take any target id, including another running
# session's tab. These are the CDP calls they make with it.
_TAB_CALLS = ("Target.attachToTarget", "Target.activateTarget", "Target.closeTarget")


def _claim(target_id):
    """Refuse another running session's tab; take over one that session has let go of.

    A tab belongs to the session whose group holds it, and is let go of once
    that session calls close_session() or its daemon is gone (it ended, the
    reaper stopped it). Ungrouped tabs and other targets are anyone's.
    """
    if not target_id:
        return
    try:
        info = _orig_cdp("Target.getTargetInfo", targetId=target_id)["targetInfo"]
    except Exception:
        raise RuntimeError(f"tab_gone: tab {target_id} was closed") from None
    sw = info["type"] == "page" and next(
        (w for w in _find_groups_workers() if w["browserContextId"] == info["browserContextId"]), None)
    sw = sw and _current(sw)
    owner = (sw and _eval_in(sw, f"bhOwner({json.dumps(target_id)})")) or {}
    key = owner.get("key")
    if not key or key == _session_key():
        return
    if not owner["done"] and _ipc.ping(key):
        raise RuntimeError(
            f'tab_locked: tab {target_id} is in the tab group "{owner.get("title")}" of session {key}, '
            "which is still running. Work in your own tabs (new_tab()); a tab is free once its session "
            "calls close_session() or ends.")
    _group_tab(target_id, sw)


_new_tab = globals()["new_tab"]


def _blank(url):
    return url in ("", "about:blank") or url.startswith(("about:blank#", "chrome://newtab", "chrome://new-tab-page"))


def _context(target_id):
    return _orig_cdp("Target.getTargetInfo", targetId=target_id)["targetInfo"]["browserContextId"]


def new_tab(url="about:blank"):
    sw = _groups_worker(wake=True, open_profile=True)
    if not sw:  # no extension: upstream's tab, ungrouped, in the last used profile
        return _new_tab(url)
    # CDP opens tabs only in the last used profile, so the tab comes from this
    # profile's worker. The daemon's own blank tab is reused when it is here,
    # and closed when it went to another profile.
    try:
        cur = _bh.current_tab()
    except RuntimeError:  # tab_gone: close_session(), or the user closed it
        cur = None
    if cur and _blank(cur["url"]) and _context(cur["targetId"]) == sw["browserContextId"]:
        tid = cur["targetId"]
    else:
        opened = _eval_in(sw, "bhOpenTab()") or {}
        if "targetId" not in opened:
            if _PROFILE:
                raise RuntimeError(f'could not open a tab in the Chrome profile "{_PROFILE}": {opened.get("error")}')
            return _new_tab(url)
        tid = opened["targetId"]
        switch_tab(tid)
        # A named daemon's own tab is about:blank; anything else may be the user's.
        if cur and cur["url"] == "about:blank" and os.environ.get("BU_NAME"):
            _orig_cdp("Target.closeTarget", targetId=cur["targetId"])
    if url != "about:blank":
        _goto_url(url)
    _group_tab(tid, sw)
    return tid


new_tab.__doc__ = _new_tab.__doc__

_goto_url = _bh.goto_url


def goto_url(url):
    if _PROFILE:
        # The daemon's first tab comes from CDP, which puts it in the last used
        # profile: navigate there and this session would be on the other
        # profile's logins.
        sw = _groups_worker()
        if not sw or _context(_bh.current_tab()["targetId"]) != sw["browserContextId"]:
            new_tab()
    return _goto_url(url)


goto_url.__doc__ = _goto_url.__doc__


# --- The agent's own input ----------------------------------------------------

# Two things are checked around each click, key press and scroll, in one page
# evaluation before the input:
#
# - Focus emulation. The daemon re-attaches silently when its CDP session
#   drops, and the new session starts without it: after close_session() and
#   new_tab(), every click did nothing (2026-11-17, when the daemon still moved
#   to a replacement tab). A hidden page is re-armed here.
# - Pages opening a tab. A target=_blank link or GET form opens its tab in
#   front and raises Chrome (2026-11-17, a Taobao link), and nothing stops that
#   once the page has asked. For the length of the input the page leaves them
#   to us, and they open as background tabs in the session's group
#   (docs/design.md). POST forms and window.open() are left alone.
_INPUT_GUARD = r"""(() => {
  if (!window.__obuLinks) {
    const newContext = (t) => !["", "_self", "_parent", "_top"].includes(t.toLowerCase())
      && !document.querySelector(`iframe[name="${CSS.escape(t)}"], frame[name="${CSS.escape(t)}"]`);
    const baseTarget = () => document.querySelector("base[target]")?.target ?? "";
    const g = window.__obuLinks = {links: []};
    const take = (e, url, rel) => {
      e.preventDefault();
      g.links.push({url, referrer: /\bnoreferrer\b/i.test(rel) ? "" : location.href});
    };
    g.click = (e) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = e.composedPath().find((n) => n.localName === "a" || n.localName === "area");
      if (!a || !a.href || a.hasAttribute("download") || /\bopener\b/i.test(a.rel)) return;
      if (newContext(a.getAttribute("target") ?? baseTarget())) take(e, a.href, a.rel);
    };
    g.submit = (e) => {
      const f = e.target, s = e.submitter, rel = f.getAttribute("rel") || "";
      if (e.defaultPrevented || /\bopener\b/i.test(rel)) return;
      if ((s?.getAttribute("formmethod") ?? f.method).toLowerCase() !== "get") return;
      if (!newContext(s?.getAttribute("formtarget") ?? f.getAttribute("target") ?? baseTarget())) return;
      const url = new URL(s?.hasAttribute("formaction") ? s.formAction : f.action);
      try { url.search = new URLSearchParams(new FormData(f, s)); } catch { return; }
      take(e, url.href, rel);
    };
    addEventListener("click", g.click);
    addEventListener("submit", g.submit);
  }
  return document.visibilityState;
})()"""
_INPUT_TAKE = """(() => {
  const g = window.__obuLinks;
  if (!g) return [];
  removeEventListener("click", g.click);
  removeEventListener("submit", g.submit);
  delete window.__obuLinks;
  return g.links;
})()"""


def _open_in_background(url, referrer):
    """A background tab of this session's profile and group; the daemon stays where it is."""
    sw = _groups_worker(wake=True)
    tid = ((sw and _eval_in(sw, "bhOpenTab()")) or {}).get("targetId")
    if not tid:
        return _orig_cdp("Target.createTarget", url=url, background=True)["targetId"]
    sid = _orig_cdp("Target.attachToTarget", targetId=tid, flatten=True)["sessionId"]
    try:  # the referrer a real click would have sent
        _orig_cdp("Page.navigate", session_id=sid, url=url, referrer=referrer,
                  referrerPolicy="strictOriginWhenCrossOrigin")
    finally:
        _orig_cdp("Target.detachFromTarget", sessionId=sid)
    _group_tab(tid, sw)
    return tid


def _agent_input(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            r = _orig_cdp("Runtime.evaluate", expression=_INPUT_GUARD, returnByValue=True)
            if r["result"].get("value") == "hidden":
                _orig_cdp("Emulation.setFocusEmulationEnabled", enabled=True)
        except Exception:
            return fn(*args, **kwargs)
        try:
            return fn(*args, **kwargs)
        finally:
            try:
                links = _orig_cdp("Runtime.evaluate", expression=_INPUT_TAKE, returnByValue=True)["result"]["value"]
            except Exception:
                links = []  # the input navigated this tab away, guard and all
            for link in links:
                tid = _open_in_background(link["url"], link["referrer"])
                print(f"opened in a background tab, switch_tab({tid!r}) to work there: {link['url']}")

    return wrapper


press_key = _agent_input(_bh.press_key)


# --- Codex-style cursor --------------------------------------------------------

_CURSOR_ON = os.environ.get("OBU_CURSOR", "").strip().lower() not in {"0", "false", "no", "off"}
_CURSOR_GLIDE_S = 0.32  # the extension's CSS transition is 0.3s


def _cursor_to(x, y):
    """Glide the page's agent cursor to (x, y); wait for it only if it actually moves."""
    if not _CURSOR_ON:
        return
    expr = (
        "(() => { const e = document.documentElement;"
        " if (!e.hasAttribute('data-browser-harness-ext')) return false;"
        " const prev = e.getAttribute('data-browser-harness-cursor') || '';"
        f" const at = '{float(x)},{float(y)}';"
        " e.setAttribute('data-browser-harness-cursor', at + ',' + Date.now());"
        " return prev !== '' && !prev.startsWith(at + ','); })()"
    )
    try:
        r = _orig_cdp("Runtime.evaluate", expression=expr, returnByValue=True)
        if r.get("result", {}).get("value"):
            time.sleep(_CURSOR_GLIDE_S)
    except Exception:
        pass


def _set_cursor_hidden(hidden):
    expr = ("document.documentElement.setAttribute('data-browser-harness-cursor-hidden','')" if hidden
            else "document.documentElement.removeAttribute('data-browser-harness-cursor-hidden')")
    try:
        _orig_cdp("Runtime.evaluate", expression=expr)
    except Exception:
        pass


_click_at_xy = _agent_input(_bh.click_at_xy)
_scroll = _agent_input(_bh.scroll)
_capture_screenshot = _bh.capture_screenshot


def click_at_xy(x, y, button="left", clicks=1):
    _cursor_to(x, y)
    return _click_at_xy(x, y, button=button, clicks=clicks)


def scroll(x, y, dy=-300, dx=0):
    _cursor_to(x, y)
    return _scroll(x, y, dy=dy, dx=dx)


def capture_screenshot(path=None, full=False, max_dim=None):
    if path:
        # A missing directory was the most common screenshot failure (36 times
        # in 10 sessions, October 2026): agents save straight into a new
        # acceptance folder.
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if not _CURSOR_ON:
        return _capture_screenshot(path, full=full, max_dim=max_dim)
    _set_cursor_hidden(True)
    try:
        return _capture_screenshot(path, full=full, max_dim=max_dim)
    finally:
        _set_cursor_hidden(False)


_js = _bh.js


def js(expression, target_id=None):
    try:
        return _js(expression, target_id=target_id)
    except RuntimeError as e:
        # Every call evaluates in the page's global scope, so a top-level
        # const/let from an earlier call makes the same name fail the next
        # time (129 failures in 8 sessions). A block gives it its own scope
        # and keeps the last statement's value as the result. Retrying is safe:
        # the redeclaration is rejected before any of the script runs.
        if "has already been declared" not in str(e):
            raise
        return _js("{\n" + expression + "\n}", target_id=target_id)


for _f, _orig in ((click_at_xy, _click_at_xy), (scroll, _scroll), (capture_screenshot, _capture_screenshot), (js, _js)):
    _f.__doc__ = _orig.__doc__
del _f, _orig


# --- Element refs ---------------------------------------------------------------

# Agents found elements in the raw accessibility tree and clicked by
# coordinates, so a click that landed on a cookie banner, or on whatever had
# taken the element's place, still read as success. A ref names one element of
# a snapshot. Each browser-harness call is its own process, so refs live in a
# file per session next to the daemon's log, with the tab and document they
# came from: backend node ids are only meaningful within one document.
_REF_ROLES = {
    "button", "link", "textbox", "searchbox", "combobox", "listbox", "option", "checkbox", "radio",
    "switch", "slider", "spinbutton", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "treeitem",
}
_REF_STATES = ("disabled", "checked", "selected", "expanded")
_REFS = _ipc.log_path(_session_key()).with_suffix(".refs")

# Before the input: the element's centre, scrolled into view, or why a click
# there would not reach it. A one-shot listener then records whether the press
# did, for _PRESS_TAKE to read after it.
_PRESS_POINT = r"""function () {
  if (!this.isConnected) return {error: "is no longer on the page"};
  let r = this.getBoundingClientRect();
  if (r.top < 0 || r.left < 0 || r.bottom > innerHeight || r.right > innerWidth) {
    this.scrollIntoView({block: "center", inline: "center", behavior: "instant"});
    r = this.getBoundingClientRect();
  }
  if (!r.width || !r.height || !this.checkVisibility({visibilityProperty: true})) return {error: "is hidden"};
  if (this.matches(":disabled")) return {error: "is disabled"};
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return {error: "is outside the viewport"};
  let hit = document.elementFromPoint(x, y);
  for (let inner; hit?.shadowRoot && (inner = hit.shadowRoot.elementFromPoint(x, y)) && inner !== hit;) hit = inner;
  const mine = [this, ...(this.labels || [])];  // a click on its label reaches a field too
  const within = (n) => { for (; n; n = n.parentNode || n.host) if (mine.includes(n)) return true; return false; };
  if (!within(hit)) {
    const what = hit ? hit.localName + (hit.id ? "#" + hit.id : "") + [...hit.classList].slice(0, 2).map((c) => "." + c).join("") : "nothing";
    return {error: `is covered by <${what}> at its centre`};
  }
  const p = window.__obuPress = {hit: false, on: (e) => { p.hit = e.composedPath().some((n) => mine.includes(n)); }};
  addEventListener("mousedown", p.on, {capture: true, once: true});
  return {x, y};
}"""
_PRESS_TAKE = """(() => {
  const p = window.__obuPress;
  if (!p) return null;
  removeEventListener("mousedown", p.on, {capture: true});
  delete window.__obuPress;
  return p.hit;
})()"""
_SELECT_TEXT = """function (clear) {
  if (this.select) {
    this.select();
    if (!clear) try { this.setSelectionRange(this.value.length, this.value.length); } catch {}
  } else {
    getSelection().selectAllChildren(this);
    if (!clear) getSelection().collapseToEnd();
  }
}"""
_CHANGED = """function () {
  this.dispatchEvent(new Event("input", {bubbles: true}));
  this.dispatchEvent(new Event("change", {bubbles: true}));
}"""


def _load_refs():
    try:
        return json.loads(_REFS.read_text())
    except (OSError, ValueError):
        return {}


def _document():
    return cdp("Page.getFrameTree")["frameTree"]["frame"]["loaderId"]


def _ax_value(node, field):
    return node.get(field, {}).get("value", "")


def _interactive():
    """(backend node id, role, name, AX node) of each interactive element of the page."""
    for n in cdp("Accessibility.getFullAXTree")["nodes"]:
        if not n.get("ignored") and _ax_value(n, "role") in _REF_ROLES and "backendDOMNodeId" in n:
            yield n["backendDOMNodeId"], _ax_value(n, "role"), _ax_value(n, "name"), n


def _describe(role, name, ax):
    props = {p["name"]: p["value"].get("value") for p in ax.get("properties", [])}
    value = _ax_value(ax, "value")
    return (f"{role} {json.dumps(name[:80], ensure_ascii=False)}"
            + (f" = {json.dumps(str(value)[:80], ensure_ascii=False)}" if value != "" else "")
            + "".join(f" [{s}]" for s in _REF_STATES if props.get(s) in (True, "true")))


def snapshot():
    """The page's interactive elements, one per line: '@e3 button "Sign in"'.

    click("@e3") and fill_input("@e5", text) take these refs. A ref keeps naming
    the same element across snapshots of the page; after a re-render it is found
    again by role and name, and refused when that is no longer exactly one
    element. Refs belong to this tab: take a new snapshot after switch_tab().
    """
    tid, doc, old = _bh.current_tab()["targetId"], _document(), _load_refs()
    known = {(e["node"], e["doc"]): r for r, e in old.get("refs", {}).items()} if old.get("target") == tid else {}
    nodes = list(_interactive())
    count = collections.Counter((role, name) for _, role, name, _ in nodes)
    n, refs, lines = old.get("next", 1), {}, []
    for node, role, name, ax in nodes:
        ref = known.get((node, doc))
        if not ref:  # numbers are never reused, so an old ref cannot name a new element
            ref, n = f"e{n}", n + 1
        refs[ref] = {"node": node, "doc": doc, "role": role, "name": name, "dup": count[role, name] > 1}
        lines.append(f"@{ref} {_describe(role, name, ax)}")
    _REFS.write_text(json.dumps({"target": tid, "next": n, "refs": refs}))
    return "\n".join(lines)


def _still(node, role, name):
    try:
        ax = cdp("Accessibility.getPartialAXTree", backendNodeId=node, fetchRelatives=False)["nodes"][0]
    except Exception:
        return False  # gone with its document or garbage-collected
    return not ax.get("ignored") and (_ax_value(ax, "role"), _ax_value(ax, "name")) == (role, name)


def _ref_node(ref):
    """The backend node id of the element ref names now, or an error saying why there is none."""
    key = ref.removeprefix("@")
    refs = _load_refs()
    e = refs.get("refs", {}).get(key)
    if not e:
        raise RuntimeError(f"unknown ref @{key}: take a snapshot() of this page first")
    if refs["target"] != _bh.current_tab()["targetId"]:
        raise RuntimeError(f"@{key} is from another tab: take a snapshot() of this one")
    doc = _document()
    if e["doc"] == doc and _still(e["node"], e["role"], e["name"]):
        return e["node"]
    what = f'@{key} ({e["role"]} {json.dumps(e["name"], ensure_ascii=False)}) is stale'
    if e["dup"]:
        raise RuntimeError(f"{what} and the snapshot had several such elements: take a new snapshot()")
    found = [node for node, role, name, _ in _interactive() if (role, name) == (e["role"], e["name"])]
    if len(found) != 1:
        raise RuntimeError(f"{what} and {len(found) or 'no'} such elements are on the page now: take a new snapshot()")
    e.update(node=found[0], doc=doc)
    _REFS.write_text(json.dumps(refs))
    return found[0]


def _call_on(node, function, *args):
    obj = cdp("DOM.resolveNode", backendNodeId=node)["object"]["objectId"]
    r = cdp("Runtime.callFunctionOn", objectId=obj, functionDeclaration=function, returnByValue=True,
            arguments=[{"value": a} for a in args])
    if "exceptionDetails" in r:
        raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description") or r["exceptionDetails"]["text"])
    return r["result"].get("value")


def _click_ref(ref):
    node = _ref_node(ref)
    at = _call_on(node, _PRESS_POINT)
    if "error" in at:
        raise RuntimeError(f"{ref} {at['error']}; nothing was clicked")
    click_at_xy(at["x"], at["y"])
    try:
        landed = _orig_cdp("Runtime.evaluate", expression=_PRESS_TAKE, returnByValue=True)["result"].get("value")
    except Exception:
        landed = None  # the click navigated away
    if landed is False:
        raise RuntimeError(f"the click at ({at['x']:.0f}, {at['y']:.0f}) landed on another element, not {ref}")
    return node


def click(ref):
    """Click an element of snapshot() by its ref, "@e3".

    Raises instead of clicking when the element is hidden, disabled or covered
    (a dialog, a banner), or when the ref no longer names one element, and when
    the press did not reach it.
    """
    _click_ref(ref)


_fill_input = _bh.fill_input


def fill_input(selector, text, clear_first=True, timeout=0.0):
    if not selector.startswith("@"):
        return _fill_input(selector, text, clear_first=clear_first, timeout=timeout)
    node = _click_ref(selector)  # focuses it, with click()'s checks
    _call_on(node, _SELECT_TEXT, clear_first)
    if clear_first:
        press_key("Backspace")
    for ch in text:
        press_key(ch)
    _call_on(node, _CHANGED)


fill_input.__doc__ = _fill_input.__doc__ + '\n    selector may be a ref from snapshot(), "@e5": clicked, then typed into.\n'


# --- Tab status ----------------------------------------------------------------

def mark_tab(status, target=None):
    """Mark a tab as held for the user, so close_session() and the reaper leave it open.

    status: "deliverable" (a result the user should look at),
            "handoff" (the user has to act here, e.g. log in or approve; the
            tab is brought to the front, since the user has to go there anyway),
            None (clear). target: a target id or tab dict; default the current tab.
    Returns False if the session-groups extension is not loaded.
    """
    if status not in ("deliverable", "handoff", None):
        raise ValueError('status must be "deliverable", "handoff" or None')
    target_id = _bh._target_id(target) if target is not None else _bh.current_tab()["targetId"]
    _claim(target_id)
    try:
        r = _call_groups_worker("bhMarkTab", target_id, status, wake=True)
        ok = bool(r) and "error" not in r
    except Exception:
        return False
    if ok and status:
        # The daemon closes its own first tab when it stops, and new_tab()
        # usually reuses that tab for work: a result marked there vanished when
        # The reaper stopped the session's daemon (2026-10-16). Hand it over;
        # its group cleanup now decides when it closes.
        try:
            _bh._send({"meta": "release_target", "target_id": target_id})
        except Exception:
            pass
    if ok and status == "handoff":
        # Agents called activate_tab() themselves for exactly this in 14 of 95
        # sessions, against the rule that nothing takes the screen.
        _bh.activate_tab(target_id)
    return ok


def close_session():
    """Close this session's tabs when its browser work is done; Chrome drops the group with them.

    Tabs marked with mark_tab() stay open for the user, in their group. Other
    sessions' tabs are never touched. Returns {"closed": n, "kept": n}, or None
    if the session-groups extension is not loaded.
    """
    try:
        r = _call_groups_worker("bhCloseSession", _session_key(), wake=True)
        return r if r and "error" not in r else None
    except Exception:
        return None
