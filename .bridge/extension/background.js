// background.js — ANBM Bridge service worker v2 (MV3)
// Relays messages between popup and content script, polls bridge for tasks,
// watches navigation for reliable page-load detection.

const BRIDGE_URL = "http://localhost:8765";

// ── Navigation Tracking ────────────────────────────────────

// Track navigation completion per tab for reliable wait-for-ready
const tabNavigations = new Map(); // tabId -> { url, completed: bool, timestamp }

chrome.webNavigation.onCompleted.addListener((details) => {
  if (details.frameId === 0) { // main frame only
    tabNavigations.set(details.tabId, {
      url: details.url,
      completed: true,
      timestamp: Date.now(),
    });
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  tabNavigations.delete(tabId);
});

function waitForNavigationComplete(tabId, timeoutMs = 15000) {
  return new Promise((resolve) => {
    const existing = tabNavigations.get(tabId);
    if (existing && existing.completed) {
      resolve(existing);
      return;
    }

    const startTime = Date.now();
    const check = () => {
      const nav = tabNavigations.get(tabId);
      if (nav && nav.completed) {
        resolve(nav);
        return;
      }
      if (Date.now() - startTime > timeoutMs) {
        resolve({ completed: false, timed_out: true });
        return;
      }
      setTimeout(check, 200);
    };
    check();
  });
}

// ── Bridge API ─────────────────────────────────────────────

async function bridgeFetch(path, options = {}) {
  const resp = await fetch(`${BRIDGE_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  return resp.json();
}

async function fetchTasks(adapter_id) {
  const url = adapter_id
    ? `/tasks?adapter_id=${encodeURIComponent(adapter_id)}`
    : `/tasks`;
  return bridgeFetch(url);
}

async function postSnapshot(data) {
  return bridgeFetch("/snapshot", { method: "POST", body: JSON.stringify(data) });
}

async function postSelectorResult(data) {
  return bridgeFetch("/selector-result", { method: "POST", body: JSON.stringify(data) });
}

async function fetchAdapterList() {
  return bridgeFetch("/adapters");
}

async function fetchAdapterManifest(adapterId) {
  return bridgeFetch(`/adapters/${adapterId}/manifest.json`);
}

// ── Message Handler ────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  function reply(data) {
    try { sendResponse(data); } catch (e) { /* ok */ }
  }

  // ── Bridge calls ──

  if (message.action === "fetch_tasks") {
    fetchTasks(message.adapter_id).then(reply).catch(err => reply({ error: err.message }));
    return true;
  }
  if (message.action === "post_snapshot") {
    postSnapshot(message.data).then(reply).catch(err => reply({ error: err.message }));
    return true;
  }
  if (message.action === "post_selector_result") {
    postSelectorResult(message.data).then(reply).catch(err => reply({ error: err.message }));
    return true;
  }
  if (message.action === "check_bridge") {
    bridgeFetch("/health")
      .then(reply)
      .catch(() => reply({ ok: false, error: "bridge offline" }));
    return true;
  }
  if (message.action === "fetch_adapters") {
    fetchAdapterList().then(reply).catch(err => reply({ error: err.message }));
    return true;
  }
  if (message.action === "fetch_manifest") {
    fetchAdapterManifest(message.adapter_id)
      .then(reply)
      .catch(err => reply({ error: err.message }));
    return true;
  }

  // ── Tab / Navigation ──

  if (message.action === "navigate_and_wait") {
    // Navigate a tab and wait for page load completion
    chrome.tabs.update(message.tabId, { url: message.url }, async () => {
      // Wait for webNavigation event
      const navResult = await waitForNavigationComplete(message.tabId, message.timeoutMs || 15000);
      reply({ navigated: true, ...navResult });
    });
    return true;
  }

  if (message.action === "create_tab") {
    chrome.tabs.create({ url: message.url, active: message.active !== false }, (tab) => {
      reply({ tabId: tab.id, url: message.url });
    });
    return true;
  }

  return false;
});
