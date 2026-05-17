// popup.js v2.1 — ANBM Bridge control panel
const BRIDGE_URL = "http://localhost:8765";
let currentTabId = null, currentUrl = "", adapters = [], currentManifest = null;
let batchRunning = false, batchStopRequested = false;
const logLines = [];

document.addEventListener("DOMContentLoaded", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab) { currentTabId = tab.id; currentUrl = tab.url || ""; }
  await checkBridgeHealth(); await loadAdapterList(); autoDetectAdapter();
});

async function checkBridgeHealth() {
  try {
    const c = new AbortController();
    const t = setTimeout(() => c.abort(), 3000);
    const r = await fetch(BRIDGE_URL + "/health", { signal: c.signal });
    clearTimeout(t);
    const d = await r.json();
    setBridgeStatus(true, "Online | " + (d.tasks_pending||0) + " tasks | " + (d.snapshots_received||0) + " snaps");
  } catch (e) { setBridgeStatus(false, e.name === "AbortError" ? "Bridge timeout" : "Bridge offline"); }
}

function setBridgeStatus(online, text) {
  document.getElementById("statusBar").className = "status-bar " + (online ? "online" : "offline");
  document.getElementById("statusDot").className = "status-dot " + (online ? "online" : "offline");
  document.getElementById("statusText").textContent = text;
  document.querySelectorAll("button").forEach(b => {
    if (!["btnClearLog","btnStopBatch"].includes(b.id)) b.disabled = !online;
  });
}

function log(msg, type) {
  type = type || "info";
  var t = new Date().toLocaleTimeString();
  logLines.push({ time: t, msg: msg, type: type });
  var cls = type === "ok" ? "log-ok" : type === "err" ? "log-err" : type === "warn" ? "log-warn" : "log-info";
  document.getElementById("logArea").innerHTML += "<div class=\"" + cls + "\">[" + t + "] " + msg + "</div>";
  document.getElementById("logArea").scrollTop = document.getElementById("logArea").scrollHeight;
}

function getBuiltinAdapterList() {
  return [
    { id: "arxiv", name: "arXiv", states: ["home","search_results","paper_detail","not_found"], verified: false },
    { id: "codeberg", name: "Codeberg", states: ["issue_detail","issue_list","not_logged_in","logged_in"], verified: false },
    { id: "devto", name: "DEV.to", states: ["article_detail","feed","not_logged_in","logged_in"], verified: false },
    { id: "douban_movie", name: "Douban Movie", states: ["movie_list","movie_detail"], verified: true },
    { id: "exercism", name: "Exercism", states: ["track_list","exercise_list","exercise_detail","not_found"], verified: false },
    { id: "github_issues", name: "GitHub Issues", states: ["issue_detail","issue_list","logged_in","not_logged_in"], verified: true },
    { id: "hackernews", name: "Hacker News", states: ["item_detail","news_list"], verified: true },
    { id: "lobsters", name: "Lobsters", states: ["story_list","story_detail","not_found"], verified: true },
    { id: "mastodon", name: "Mastodon", states: ["feed_partial","feed_exhausted"], verified: false },
    { id: "mdn", name: "MDN Web Docs", states: ["article","search_results","not_found"], verified: false },
    { id: "pypi", name: "PyPI", states: ["project_list","project_detail","not_found"], verified: true },
    { id: "reddit", name: "Reddit", states: ["post_detail","subreddit_feed","logged_in","not_logged_in"], verified: true },
    { id: "stackoverflow", name: "Stack Overflow", states: ["question_list","question_detail","search_results","not_found"], verified: true },
    { id: "unsplash", name: "Unsplash", states: ["photo_grid","photo_detail"], verified: false },
    { id: "wikipedia", name: "Wikipedia", states: ["article","special_page"], verified: false },
  ];
}

// Per-adapter selector definitions for the verify button
function getSelectorsForState(adapterId, state) {
  var map = {
    "lobsters": {
      "story_list": ["ol.stories.list", "ol.stories.list > li.story", "a.u-url", "a.tag", ".voters .upvoter", ".domain", ".byline .u-author", ".comments_label a", "nav.morelink a", "div.story_content"],
      "story_detail": ["div.story_content", "textarea", "ol.stories.list"]
    },
    "pypi": {
      "project_list": [".package-snippet", ".package-snippet__title", ".package-snippet__description", "#search"]
    },
    "stackoverflow": {
      "question_list": [".s-post-summary", "h3 a.s-link", "[rel='tag']", ".s-pagination", ".s-post-summary--stats-item-number"]
    },
    "arxiv": {
      "search_results": [".arxiv-result", ".title", ".authors", ".abstract", "a[href^='/abs/']"]
    },
    "wikipedia": {
      "article": ["h1#firstHeading", "div.mw-parser-output", "h2", "table.infobox", "a.interlanguage-link-target"]
    }
  };
  if (map[adapterId] && map[adapterId][state]) return map[adapterId][state];
  return null;
}

async function loadAdapterList() {
  try {
    var resp = await chrome.runtime.sendMessage({ action: "fetch_adapters" });
    if (resp && resp.adapters && resp.adapters.length > 0) { adapters = resp.adapters; log("Loaded " + adapters.length + " adapters from bridge", "ok"); }
    else throw new Error("empty");
  } catch (e) {
    log("Using built-in adapter list", "warn");
    adapters = getBuiltinAdapterList();
  }
  renderAdapterSelect(); renderBatchList();
}

function renderAdapterSelect() {
  var sel = document.getElementById("adapterSelect");
  sel.innerHTML = '<option value="">-- select --</option>';
  for (var i = 0; i < adapters.length; i++) {
    var a = adapters[i];
    sel.innerHTML += '<option value="' + a.id + '">' + a.id + (a.verified ? " v" : "") + '</option>';
  }
}

async function autoDetectAdapter() {
  if (!currentUrl) return;
  var best = null, bestScore = 0;
  for (var i = 0; i < adapters.length; i++) {
    var a = adapters[i];
    if (!a.manifest || !a.manifest.url_patterns) continue;
    for (var j = 0; j < a.manifest.url_patterns.length; j++) {
      var p = a.manifest.url_patterns[j];
      var reStr = p.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*");
      try { if (new RegExp(reStr, "i").test(currentUrl) && p.length > bestScore) { bestScore = p.length; best = a; } } catch (e) {}
    }
  }
  if (best) { selectAdapter(best); log("Auto-detected: " + best.id, "ok"); }
  else {
    try {
      var host = new URL(currentUrl).hostname;
      var parts = host.split(".");
      var guess = parts.length >= 2 ? parts[parts.length-2] : host;
      var match = adapters.find(function(a) { return a.id.indexOf(guess) >= 0 || guess.indexOf(a.id) >= 0; });
      if (match) { selectAdapter(match); log("Domain guess: " + match.id); }
    } catch (e) {}
  }
  document.getElementById("adapterSelect").addEventListener("change", function(e) {
    document.getElementById("adapterId").value = e.target.value;
    onAdapterSelected(e.target.value);
  });
  document.getElementById("adapterId").addEventListener("input", function(e) {
    document.getElementById("adapterSelect").value = e.target.value;
    onAdapterSelected(e.target.value);
  });
}

function selectAdapter(a) {
  document.getElementById("adapterSelect").value = a.id;
  document.getElementById("adapterId").value = a.id;
  onAdapterSelected(a.id);
}

async function onAdapterSelected(adapterId) {
  if (!adapterId) { currentManifest = null; renderStateSelect([]); return; }
  try {
    var resp = await chrome.runtime.sendMessage({ action: "fetch_manifest", adapter_id: adapterId });
    if (resp && !resp.error && resp.states) { currentManifest = resp; renderStateSelect(Object.keys(resp.states)); return; }
  } catch (e) {}
  currentManifest = null;
  var cached = adapters.find(function(a) { return a.id === adapterId; });
  renderStateSelect(cached && cached.states ? cached.states : []);
}

function renderStateSelect(states) {
  var sel = document.getElementById("stateSelect");
  sel.innerHTML = '<option value="">auto-detect state</option>';
  for (var i = 0; i < states.length; i++) {
    sel.innerHTML += '<option value="' + states[i] + '">' + states[i] + '</option>';
  }
}

function getAdapterId() {
  return document.getElementById("adapterId").value.trim() || document.getElementById("adapterSelect").value;
}

async function sendToContent(action, params) {
  if (!currentTabId) { log("No active tab", "err"); return null; }
  params = params || {};
  try { return await chrome.tabs.sendMessage(currentTabId, { action: action, ...params }); }
  catch (e) { log("Content script error. Refresh page.", "err"); return null; }
}

// ── Scan ──
document.getElementById("btnScan").addEventListener("click", async () => {
  var id = getAdapterId();
  if (!id) { log("Select an adapter first", "err"); return; }
  var stateHint = document.getElementById("stateSelect").value || undefined;
  log("Scan: " + id + (stateHint ? " [" + stateHint + "]" : ""));
  var snap = await sendToContent("capture_snapshot", { options: { maxDepth: 10 } });
  if (!snap) return;
  if (snap.error) { log("Scan failed: " + snap.error, "err"); return; }
  log("DOM: " + (snap.elements ? snap.elements.length : 0) + " elements, " + (snap.main_landmarks ? snap.main_landmarks.length : 0) + " landmarks");
  try {
    var data = { adapter_id: id, url: snap.url || currentUrl, title: snap.title || document.title,
      timestamp: new Date().toISOString(), elements: snap.elements || [], main_landmarks: snap.main_landmarks || [],
      body_class: snap.body_class || "", state_hint: stateHint || null };
    var resp = await chrome.runtime.sendMessage({ action: "post_snapshot", data: data });
    log(resp && resp.ok ? "Uploaded: " + resp.path : "Upload failed", resp && resp.ok ? "ok" : "err");
  } catch (e) { log("Upload error: " + e.message, "err"); }
});

// ── Quick test ──
document.getElementById("btnQuickTest").addEventListener("click", async () => {
  var sel = document.getElementById("selectorInput").value.trim();
  if (!sel) { log("Enter a selector", "err"); return; }
  log("Test: " + sel);
  var r = await sendToContent("test_selectors", { selectors: [sel] });
  if (!r || !r.results) return;
  var s = r.results[0];
  if (s.found) { log("OK " + s.count + " matches", "ok"); if (s.sample_html) log("  " + s.sample_html.substring(0,100)); }
  else { log("NOT FOUND: " + (s.error||""), "err"); }
});

// ── Verify ──
document.getElementById("btnVerify").addEventListener("click", async () => {
  var id = getAdapterId();
  if (!id) { log("Select adapter", "err"); return; }
  log("=== Verify: " + id + " ===", "info");
  var snap = await sendToContent("capture_snapshot", { options: { maxDepth: 10 } });
  if (!snap || snap.error) { log("Scan failed", "err"); return; }
  var stateHint = document.getElementById("stateSelect").value || undefined;
  await chrome.runtime.sendMessage({ action: "post_snapshot", data: {
    adapter_id: id, url: snap.url || currentUrl, title: snap.title || "",
    timestamp: new Date().toISOString(), elements: snap.elements || [],
    main_landmarks: snap.main_landmarks || [], body_class: snap.body_class || "",
    state_hint: stateHint || null }});

  var currentState = document.getElementById("stateSelect").value || "unknown";
  log("State: " + currentState, "ok");

  var selectors = getSelectorsForState(id, currentState);
  if (!selectors || selectors.length === 0) selectors = ["body"];

  log("Testing " + selectors.length + " selectors...");
  var selResults = await sendToContent("test_selectors", { selectors: selectors });
  var results = (selResults && selResults.results ? selResults.results : []).map(function(r) {
    return { selector: r.selector, found: r.found, count: r.count, sample_html: r.sample_html ? r.sample_html.substring(0,200) : null };
  });
  var found = results.filter(function(r) { return r.found; }).length;
  log("Result: " + found + "/" + results.length + " matched", found === results.length ? "ok" : "warn");

  var taskId = "av_" + id + "_" + Date.now();
  await chrome.runtime.sendMessage({ action: "post_selector_result", data: {
    task_id: taskId, adapter_id: id, results: results, url: currentUrl, detected_state: currentState }});
  renderVerifyResult(id, results);
});

function renderVerifyResult(adapterId, results) {
  var ok = results.filter(function(r) { return r.found; }).length;
  var total = results.length;
  var c = document.getElementById("batchList");
  c.innerHTML += '<div class="adapter-item"><span>' + adapterId + '</span><span class="badge ' + (ok===total?'badge-ok':'badge-fail') + '">' + ok + '/' + total + '</span></div>';
}

// ── Batch scan ──
document.getElementById("btnBatchScan").addEventListener("click", async () => {
  if (batchRunning) return;
  batchRunning = true; batchStopRequested = false;
  document.getElementById("btnStopBatch").style.display = "inline-block";
  document.getElementById("btnBatchScan").disabled = true;
  var unverified = adapters.filter(function(a) { return !a.verified; });
  log("Batch: " + unverified.length + " unverified", "info");
  document.getElementById("batchProgressBar").style.display = "block";
  for (var i = 0; i < unverified.length; i++) {
    if (batchStopRequested) { log("Stopped", "warn"); break; }
    var a = unverified[i];
    var url = "https://" + a.id + ".org";
    log("[" + (i+1) + "/" + unverified.length + "] " + a.id + " -> " + url);
    document.getElementById("batchStatus").textContent = (i+1) + "/" + unverified.length + ": " + a.id;
    document.getElementById("batchProgressFill").style.width = ((i+1)/unverified.length*100) + "%";
    var tr = await chrome.runtime.sendMessage({ action: "create_tab", url: url, active: true });
    if (!tr || !tr.tabId) { log("Tab failed: " + a.id, "err"); continue; }
    await chrome.runtime.sendMessage({ action: "navigate_and_wait", tabId: tr.tabId, url: url, timeoutMs: 15000 });
    await new Promise(function(r) { setTimeout(r, 2000); });
    try {
      var snap = await chrome.tabs.sendMessage(tr.tabId, { action: "capture_snapshot", options: { maxDepth: 10 } });
      if (snap && !snap.error) {
        await chrome.runtime.sendMessage({ action: "post_snapshot", data: {
          adapter_id: a.id, url: url, title: snap.title || "", timestamp: new Date().toISOString(),
          elements: snap.elements || [], main_landmarks: snap.main_landmarks || [],
          body_class: snap.body_class || "", batch_scan: true }});
        log("  " + a.id + ": " + (snap.elements?snap.elements.length:0) + " elements", "ok");
        a.verified = true;
      } else { log("  " + a.id + ": scan failed", "err"); }
    } catch (e) { log("  " + a.id + ": error - " + e.message, "err"); }
    try { chrome.tabs.remove(tr.tabId); } catch (e) {}
    await new Promise(function(r) { setTimeout(r, 1000); });
  }
  batchRunning = false;
  document.getElementById("btnStopBatch").style.display = "none";
  document.getElementById("btnBatchScan").disabled = false;
  document.getElementById("batchProgressBar").style.display = "none";
  document.getElementById("batchStatus").textContent = "Done";
  renderBatchList();
  log("Batch complete", "ok");
});

document.getElementById("btnStopBatch").addEventListener("click", function() { batchStopRequested = true; log("Stopping...", "warn"); });

function renderBatchList() {
  var c = document.getElementById("batchList");
  var h = "";
  for (var i = 0; i < adapters.length; i++) {
    var a = adapters[i];
    h += '<div class="adapter-item"><span>' + a.id + '</span><span class="badge ' + (a.verified?'badge-ok':'badge-warn') + '">' + (a.verified?'ok':'pending') + '</span></div>';
  }
  c.innerHTML = h || '<div style="color:#9ca3af;font-size:11px;">Loading...</div>';
}

document.getElementById("btnUploadLog").addEventListener("click", async () => {
  try {
    await fetch(BRIDGE_URL + "/snapshot", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ adapter_id: "_session_log", url: currentUrl, title: "log", timestamp: new Date().toISOString(), elements: [], session_log: logLines }) });
    log("Log uploaded", "ok");
  } catch (e) { log("Upload failed", "err"); }
});

document.getElementById("btnClearLog").addEventListener("click", function() {
  document.getElementById("logArea").innerHTML = "";
  logLines.length = 0;
  log("Cleared");
});
