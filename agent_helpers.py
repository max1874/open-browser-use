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
a different target (new_tab / switch_tab / ensure_real_tab).

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
BH_CURSOR=0 turns the cursor off. mark_tab() marks a tab as "deliverable" or
"handoff"; close_session() closes the session's tabs when its browser work is
done, keeping the marked ones.
"""

import json
import os
import time

import browser_harness.helpers as _bh

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
_GROUPS_API = 8  # must match self.bhApi in extension/bh_session_groups_sw.js


def _session_key():
    return os.environ.get("BU_NAME") or "default"


def _find_groups_worker():
    infos = _orig_cdp("Target.getTargets")["targetInfos"]
    return next((t for t in infos if t["type"] == "service_worker" and t["url"].endswith(_GROUPS_SW)), None)


def _wait_groups_worker(wake):
    """The worker sleeps when idle and wakes on tabs.onCreated. new_tab() has
    just created a tab; otherwise wake=True opens (and closes) a background
    about:blank for that."""
    sw = _find_groups_worker()
    if sw or not wake:
        for _ in range(20):  # give it ~2s
            if sw:
                return sw
            time.sleep(0.1)
            sw = _find_groups_worker()
        return None
    waker = _orig_cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
    try:
        return _wait_groups_worker(wake=False)
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


def _call_groups_worker(fn, *args, wake=False):
    """Call fn(*args) in the session-groups extension's worker; None if it never shows up."""
    sw = _wait_groups_worker(wake)
    if not sw:
        return None
    if _eval_in(sw, "self.bhApi") != _GROUPS_API:
        # Stale worker script: reload the extension and use the fresh worker.
        # A reload clears storage.session, i.e. every session's tab status
        # (tab ids survive it), so carry them across.
        status = _eval_in(sw, "chrome.storage.session.get('status').then(r => r.status || {})") or {}
        try:
            _eval_in(sw, "chrome.runtime.reload()")
        except Exception:
            pass  # the reload tears down the session it was sent on
        time.sleep(0.5)
        sw = _wait_groups_worker(wake=True)
        if not sw or _eval_in(sw, "self.bhApi") != _GROUPS_API:
            return None
        if status:
            _eval_in(sw, f"chrome.storage.session.set({{status: {json.dumps(status)}}})")
    return _eval_in(sw, f"{fn}({', '.join(json.dumps(a) for a in args)})")


def _group_tab(target_id):
    """Put the tab into this session's group via the session-groups extension."""
    try:
        key = _session_key()
        agent = {"cc": "Claude", "cx": "Codex"}.get(key.split("-")[0], key)
        default_title = f"{agent} · {os.path.basename(os.getcwd()) or '/'}"
        _call_groups_worker("bhGroup", target_id, key, default_title)
    except Exception:
        pass


def name_session(title):
    """Name this session's tab group, Codex style: emoji picked for the task + a short task name, e.g. "🔑 Sign up for Tiingo".

    Call it once when browser work starts (before or after the first new_tab()).
    The name sticks to the session, so a group recreated later gets it back.
    Returns False if the session-groups extension is not loaded.
    """
    try:
        return _call_groups_worker("bhNameSession", _session_key(), str(title), wake=True) is not None
    except Exception:
        return False


_new_tab = globals()["new_tab"]


def _recover_closed_tab():
    """If the daemon's tab is gone, let it attach to its replacement now; True if it did.

    After close_session() (or the user closing the tab), the daemon's next
    page-level call finds its session stale and opens a fresh about:blank.
    Upstream new_tab() makes such calls (focus emulation, unmarking the old
    tab) and then opens its own tab as well, so that about:blank was left
    ungrouped, outside close_session() and bh-reap, until the daemon stopped
    (2026-10-16: one per session in the agent Chrome). Triggering the
    replacement first lets new_tab() reuse it.
    """
    try:
        _bh.current_tab()
        return False
    except Exception:
        pass
    try:
        cdp("Runtime.evaluate", expression="0")
        _bh.current_tab()
        return True
    except Exception:
        return False


def new_tab(url="about:blank"):
    if _recover_closed_tab() and url == "about:blank":
        tid = _bh.current_tab()["targetId"]  # upstream new_tab("about:blank") would open another
    else:
        tid = _new_tab(url)
    _group_tab(tid)
    return tid


new_tab.__doc__ = _new_tab.__doc__


# --- Codex-style cursor --------------------------------------------------------

_CURSOR_ON = os.environ.get("BH_CURSOR", "").strip().lower() not in {"0", "false", "no", "off"}
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


_click_at_xy = _bh.click_at_xy
_scroll = _bh.scroll
_capture_screenshot = _bh.capture_screenshot


def click_at_xy(x, y, button="left", clicks=1):
    _cursor_to(x, y)
    return _click_at_xy(x, y, button=button, clicks=clicks)


def scroll(x, y, dy=-300, dx=0):
    _cursor_to(x, y)
    return _scroll(x, y, dy=dy, dx=dx)


def capture_screenshot(path=None, full=False, max_dim=None):
    if not _CURSOR_ON:
        return _capture_screenshot(path, full=full, max_dim=max_dim)
    _set_cursor_hidden(True)
    try:
        return _capture_screenshot(path, full=full, max_dim=max_dim)
    finally:
        _set_cursor_hidden(False)


for _f, _orig in ((click_at_xy, _click_at_xy), (scroll, _scroll), (capture_screenshot, _capture_screenshot)):
    _f.__doc__ = _orig.__doc__
del _f, _orig


# --- Tab status ----------------------------------------------------------------

def mark_tab(status, target=None):
    """Mark a tab as held for the user, so close_session() and bh-reap leave it open.

    status: "deliverable" (a result the user should look at),
            "handoff" (the user has to act here, e.g. log in or approve),
            None (clear). target: a target id or tab dict; default the current tab.
    Returns False if the session-groups extension is not loaded.
    """
    if status not in ("deliverable", "handoff", None):
        raise ValueError('status must be "deliverable", "handoff" or None')
    target_id = _bh._target_id(target) if target is not None else _bh.current_tab()["targetId"]
    try:
        r = _call_groups_worker("bhMarkTab", target_id, status, wake=True)
        ok = bool(r) and "error" not in r
    except Exception:
        return False
    if ok and status:
        # The daemon closes its own first tab when it stops, and new_tab()
        # usually reuses that tab for work: a result marked there vanished when
        # bh-reap stopped the session's daemon (2026-10-16). Hand it over;
        # bh-reap's group cleanup now decides when it closes.
        try:
            _bh._send({"meta": "release_target", "target_id": target_id})
        except Exception:
            pass
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
