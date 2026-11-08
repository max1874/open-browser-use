// Called by agent_helpers.py over CDP (Runtime.evaluate on this worker):
//   bhProfile() / bhSetProfile(name, targetId)  which agent profile this is (docs/profiles.md);
//                                         targetId is the tab of the window opened to find out
//   bhOpenTab()                           new_tab(): a background tab in this profile
//   bhGroup(targetId, key, defaultTitle)  after every new_tab(): put the tab in its session's group
//   bhNameSession(key, title)             name_session(): retitle the session's group
//   bhMarkTab(targetId, status)           mark_tab(): "deliverable" / "handoff" keeps the tab open, null clears
//   bhCloseSession(key)                   close_session(): close the session's tabs except marked ones
//   bhSessionKeys() / bhReapSession(key, all)  libexec/reap.py: close an ended session's tabs
// key is BU_NAME, one per agent session.
//
// CDP has no tab-group API, and chrome.tabs has no CDP targetId, so the bridge
// is chrome.debugger.getTargets(), which lists both ids. It does not attach,
// so no "is debugging this browser" bar appears.

// Every profile's worker must be reachable over CDP at any time. An idle
// worker stops after 30 seconds, and one in a profile other than the last used
// cannot be woken from CDP, which opens tabs only in that one. Any extension
// API call resets the idle timer, so this one keeps it running (Chrome 156,
// 2026-11-05: alive after 77 s idle, a worker without it gone). onStartup
// starts it when its profile opens; onCreated lets agent_helpers.py wake an
// older version of this worker by opening a tab.
chrome.runtime.onStartup.addListener(() => {});
chrome.tabs.onCreated.addListener(() => {});
setInterval(() => chrome.runtime.getPlatformInfo(), 20e3);

// agent_helpers.py checks this before calling in and runs chrome.runtime.reload()
// on a mismatch: after a reload via CDP, Chrome can keep running the previous
// worker script even though the manifest is new (seen 2026-10-10, Chrome 154).
// Bump it with agent_helpers.py's _GROUPS_API whenever the functions change.
self.bhApi = 10;

const COLORS = ["blue", "red", "yellow", "green", "pink", "purple", "cyan", "orange"];

function colorFor(key) {
  let h = 0;
  for (const c of key) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return COLORS[h % COLORS.length];
}

// { [key]: { groupId?, title? } } — the title is kept so a group recreated
// after its last tab closed gets the session's name back.
async function sessions() {
  return (await chrome.storage.local.get("sessions")).sessions || {};
}

async function saveSession(key, patch) {
  const all = await sessions();
  all[key] = { ...all[key], ...patch };
  await chrome.storage.local.set({ sessions: all });
}

async function liveGroup(groupId) {
  if (groupId === undefined) return null;
  try {
    return await chrome.tabGroups.get(groupId);
  } catch {
    return null;
  }
}

// The profile name ("Work"), given by agent_helpers.py when it opened a window
// of this profile to find its worker; Chrome tells an extension nothing about
// its profile. That window's tab is the next one bhOpenTab() hands out.
self.bhProfile = async () => (await chrome.storage.local.get("profile")).profile || null;
let spare; // that tab's id; the worker keeps itself running (above), so it is not lost
self.bhSetProfile = async (name, targetId) => {
  await chrome.storage.local.set({ profile: name });
  spare = await tabIdOf(targetId);
  return { profile: name };
};

// A background tab in this profile: the spare one if it is still an empty
// ungrouped tab, else a new one in its last focused window, or in a new
// unfocused window when it has none. Returns its CDP target id.
self.bhOpenTab = async () => {
  const id = spare; // taken before any await, so two sessions never get the same tab
  spare = undefined;
  let tab = id === undefined ? null : await chrome.tabs.get(id).catch(() => null);
  if (tab && (tab.groupId >= 0 || !/^(chrome:\/\/newtab|about:blank)/.test(tab.url || tab.pendingUrl))) tab = null;
  if (!tab) {
    try {
      const win = await chrome.windows.getLastFocused({ windowTypes: ["normal"] });
      tab = await chrome.tabs.create({ windowId: win.id, url: "about:blank", active: false });
    } catch {
      tab = (await chrome.windows.create({ url: "about:blank", focused: false })).tabs[0];
    }
  }
  for (let i = 0; i < 40; i++) {
    const target = (await chrome.debugger.getTargets()).find((t) => t.tabId === tab.id);
    if (target) return { targetId: target.id };
    await new Promise((r) => setTimeout(r, 50));
  }
  return { error: "no target for the new tab" };
};

self.bhGroup = async (targetId, key, defaultTitle) => {
  const tabId = await tabIdOf(targetId);
  if (tabId === undefined) return { error: "tab not found" };
  const tab = await chrome.tabs.get(tabId);

  const session = (await sessions())[key] || {};
  let groupId = (await liveGroup(session.groupId))?.id;
  if (groupId !== undefined) {
    if (tab.groupId !== groupId) await chrome.tabs.group({ groupId, tabIds: [tab.id] });
  } else {
    groupId = await chrome.tabs.group({ tabIds: [tab.id], createProperties: { windowId: tab.windowId } });
    await chrome.tabGroups.update(groupId, { title: session.title || defaultTitle, color: colorFor(key) });
    await saveSession(key, { groupId });
  }
  return { groupId };
};

async function tabIdOf(targetId) {
  const target = (await chrome.debugger.getTargets()).find((t) => t.id === targetId);
  return target ? target.tabId : undefined;
}

// Tab status is kept here, not in the page, so it survives navigation.
// { [tabId]: "deliverable" | "handoff" }
async function statuses() {
  return (await chrome.storage.session.get("status")).status || {};
}

self.bhMarkTab = async (targetId, status) => {
  const tabId = await tabIdOf(targetId);
  if (tabId === undefined) return { error: "tab not found" };
  const all = await statuses();
  if (status) all[tabId] = status;
  else delete all[tabId];
  await chrome.storage.session.set({ status: all });
  chrome.tabs.sendMessage(tabId, { type: "bh-status", status: status || null }).catch(() => {});
  return { tabId };
};

chrome.tabs.onRemoved.addListener(async (tabId) => {
  const all = await statuses();
  if (tabId in all) {
    delete all[tabId];
    await chrome.storage.session.set({ status: all });
  }
});

self.bhNameSession = async (key, title) => {
  await saveSession(key, { title });
  const group = await liveGroup((await sessions())[key].groupId);
  if (group) await chrome.tabGroups.update(group.id, { title });
  return { groupId: group ? group.id : null };
};

// Closes the session's tabs except those marked for the user (deliverable /
// handoff); Chrome drops the group with its last tab. Only this session's
// group: other sessions' tabs are never touched.
self.bhCloseSession = async (key) => {
  const group = await liveGroup((await sessions())[key]?.groupId);
  if (!group) return { closed: 0, kept: 0 };
  const tabs = await chrome.tabs.query({ groupId: group.id });
  const marked = await statuses();
  const close = tabs.filter((t) => !marked[t.id]).map((t) => t.id);
  // Not awaited: closing a profile's last window ends this worker before it
  // could answer (2026-11-08).
  if (close.length) chrome.tabs.remove(close).catch(() => {});
  return { closed: close.length, kept: tabs.length - close.length };
};

// For libexec/reap.py, on sessions that have ended: close_session() on their
// behalf (marked tabs too when all is true), and forget the session once
// nothing of its group is left. Agents only call close_session() when they
// remember to, and marked tabs never closed at all (2026-10-13).
self.bhSessionKeys = async () => Object.keys(await sessions());

self.bhReapSession = async (key, all) => {
  const known = await sessions();
  const group = await liveGroup(known[key]?.groupId);
  let closed = 0, kept = 0;
  if (group) {
    const tabs = await chrome.tabs.query({ groupId: group.id });
    const marked = await statuses();
    const close = tabs.filter((t) => all || !marked[t.id]).map((t) => t.id);
    if (close.length) await chrome.tabs.remove(close);
    closed = close.length;
    kept = tabs.length - close.length;
  }
  if (!kept) {
    const latest = await sessions();
    delete latest[key];
    await chrome.storage.local.set({ sessions: latest });
  }
  return { closed, kept };
};

// bh_active_tab.js asks for its tab's status when it loads.
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === "bh-get-status") {
    statuses().then((all) => reply({ status: sender.tab ? all[sender.tab.id] || null : null }));
    return true;
  }
});
