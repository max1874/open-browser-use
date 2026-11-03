// A glowing pointer on the driven tab that glides to each click_at_xy()/scroll()
// target before the input lands, so a person watching sees where the agent acts.
//
// No favicon marks: the pointer favicon outlived the agent's turn, so it said
// nothing about whether an agent is driving the tab right now, and Chrome
// saved every mark as the page's icon in history (removed 2026-10-31).
//
// Signals, all on <html> so they cross from the page world into this one:
//   data-browser-harness-agent          set by our browser-harness fork on the attached tab
//   data-browser-harness-cursor="x,y,n" set by agent_helpers.py before a click/scroll
//   data-browser-harness-cursor-hidden  set by agent_helpers.py around screenshots
// Tab status (mark_tab) lives in the worker; a marked tab hides the pointer.

const AGENT = "data-browser-harness-agent";
const CURSOR = "data-browser-harness-cursor";
const HIDDEN = "data-browser-harness-cursor-hidden";
const READY = "data-browser-harness-ext"; // tells agent_helpers.py the cursor will animate

const GLOW = "#339cff";
// The agent attribute stays on a tab long after the agent stops acting, so the
// pointer fades on its own once no click or scroll has moved it for this long.
const IDLE_MS = 10000;

const html = document.documentElement;
let status = null; // "deliverable" | "handoff" | null, from the worker

let cursor = null; // { host, mover, placed }
let idleTimer;

function ensureCursor() {
  if (cursor && cursor.host.isConnected) return cursor;
  const host = document.createElement("div");
  host.style.cssText = "all:initial;position:fixed;inset:0;pointer-events:none;z-index:2147483646;display:none";
  const root = host.attachShadow({ mode: "closed" });
  // A plain arrow whose tip is the SVG origin, so translating the box to the
  // point puts the tip on it; a two-layer glow keeps it visible on any page.
  root.innerHTML = `<style>
    .m{position:absolute;left:0;top:0;width:20px;height:24px;will-change:transform}
    .m.go{transition:transform .3s cubic-bezier(.2,.8,.2,1)}
    svg{display:block;overflow:visible;
      filter:drop-shadow(0 0 6px color-mix(in srgb,${GLOW} 90%,transparent)) drop-shadow(0 0 15px color-mix(in srgb,${GLOW} 48%,transparent))}
    @media print{:host{display:none}}
  </style><div class="m"><svg width="20" height="24" viewBox="0 0 20 24">
    <path d="M0 0V18L4.6 13.8L8 21.4L11.2 20L7.9 12.6H14Z" fill="#111" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/>
  </svg></div>`;
  html.appendChild(host);
  cursor = { host, mover: root.querySelector(".m"), placed: false };
  return cursor;
}

function renderCursor() {
  clearTimeout(idleTimer);
  const at = (html.getAttribute(CURSOR) || "").split(",").map(Number); // x, y, Date.now() of the move
  const left = at.length === 3 ? at[2] + IDLE_MS - Date.now() : 0;
  const shown = html.hasAttribute(AGENT) && !status && !html.hasAttribute(HIDDEN) && left > 0;
  if (!shown) {
    if (cursor) cursor.host.style.display = "none";
    return;
  }
  const [x, y] = at;
  const c = ensureCursor();
  // First appearance lands in place; later moves glide.
  c.mover.classList.toggle("go", c.placed);
  c.mover.style.transform = `translate3d(${x}px, ${y}px, 0)`;
  c.host.style.display = "block";
  c.placed = true;
  idleTimer = setTimeout(renderCursor, left);
}

html.setAttribute(READY, "");
new MutationObserver(renderCursor).observe(html, { attributes: true, attributeFilter: [AGENT, CURSOR, HIDDEN] });

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.type === "bh-status") {
    status = msg.status || null;
    renderCursor();
  }
});

chrome.runtime
  .sendMessage({ type: "bh-get-status" })
  .then((r) => {
    status = (r && r.status) || null;
  })
  .catch(() => {})
  .finally(renderCursor);
