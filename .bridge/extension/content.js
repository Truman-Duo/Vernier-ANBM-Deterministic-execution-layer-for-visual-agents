// content.js — ANBM Bridge DOM scanner & selector tester (v2)
// Injected into every page. Listens for commands from popup.

(function () {
  "use strict";

  // ── Sanitization ──────────────────────────────────────────

  function sanitize(str) {
    // Escape special characters that break JSON strings.
    // This was the #1 bug: DOM text with unescaped quotes, backslashes,
    // or control chars produced malformed JSON on large pages.
    if (str == null) return "";
    return String(str)
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"')
      .replace(/\n/g, "\\n")
      .replace(/\r/g, "\\r")
      .replace(/\t/g, "\\t")
      .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, ""); // control chars
  }

  // ── DOM Snapshot ─────────────────────────────────────────

  function captureDOMSnapshot(options = {}) {
    const maxDepth = options.maxDepth || 12;
    const maxChildren = options.maxChildren || 50;
    const maxTextLen = options.maxTextLen || 200;
    const includeHidden = options.includeHidden || false;

    function isVisible(el) {
      if (includeHidden) return true;
      const style = window.getComputedStyle(el);
      return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
    }

    function getRole(el) {
      return el.getAttribute("role") || el.getAttribute("aria-role") || "";
    }

    function getAria(el) {
      const aria = {};
      for (const attr of el.attributes) {
        if (attr.name.startsWith("aria-")) {
          aria[attr.name] = sanitize(attr.value);
        }
      }
      return aria;
    }

    function getRelevantAttrs(el) {
      const relevant = ["id", "class", "name", "type", "href", "src", "alt",
        "title", "placeholder", "value", "data-testid", "data-id", "data-short-id",
        "data-controller", "data-se-page", "rel", "itemprop"];
      const attrs = {};
      for (const key of relevant) {
        const val = el.getAttribute(key);
        if (val !== null && val !== "") {
          attrs[key] = sanitize(val.length > 500 ? val.substring(0, 500) + "..." : val);
        }
      }
      return attrs;
    }

    function extractText(el) {
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        return sanitize(el.getAttribute("placeholder") || el.value || "");
      }
      if (el.tagName === "IMG") {
        return sanitize(el.getAttribute("alt") || "");
      }
      let text = "";
      for (const child of el.childNodes) {
        if (child.nodeType === Node.TEXT_NODE) {
          text += child.textContent.trim();
        }
      }
      return sanitize(text.substring(0, maxTextLen));
    }

    function walk(el, depth) {
      if (depth > maxDepth) return null;
      if (!isVisible(el)) return null;

      const node = {
        tag: el.tagName.toLowerCase(),
        role: getRole(el),
        text: extractText(el),
        attrs: getRelevantAttrs(el),
      };

      const aria = getAria(el);
      if (Object.keys(aria).length > 0) {
        node.aria = aria;
      }

      const children = [];
      let count = 0;
      for (const child of el.children) {
        if (count >= maxChildren) break;
        const childNode = walk(child, depth + 1);
        if (childNode) {
          children.push(childNode);
          count++;
        }
      }
      if (children.length > 0) {
        node.children = children;
      }

      return node;
    }

    const body = document.body;
    if (!body) return { error: "no body element" };

    const elements = [];
    let count = 0;
    for (const child of body.children) {
      if (count >= maxChildren) break;
      const node = walk(child, 1);
      if (node) {
        elements.push(node);
        count++;
      }
    }

    return {
      url: sanitize(window.location.href),
      title: sanitize(document.title),
      elements,
      body_class: sanitize(body.className || ""),
      main_landmarks: findLandmarks(),
    };
  }

  function findLandmarks() {
    const landmarks = [];
    const roles = ["main", "navigation", "banner", "contentinfo", "complementary", "search", "form"];
    for (const role of roles) {
      const el = document.querySelector('[role="' + role + '"]');
      if (el) {
        landmarks.push({
          role,
          tag: el.tagName.toLowerCase(),
          id: el.id || null,
          class: sanitize((el.className || "").substring(0, 100)),
        });
      }
    }
    return landmarks;
  }

  // ── Page Ready Detection ──────────────────────────────────

  function waitForReady(options = {}) {
    // options: { selector: string | null, timeoutMs: number }
    const timeoutMs = options.timeoutMs || 10000;
    const selector = options.selector || null;

    return new Promise((resolve) => {
      if (document.readyState === "complete") {
        if (!selector || document.querySelector(selector)) {
          resolve({ ready: true, url: window.location.href });
          return;
        }
      }

      let resolved = false;
      const timer = setTimeout(() => {
        if (!resolved) {
          resolved = true;
          observer.disconnect();
          resolve({
            ready: document.readyState === "complete",
            url: window.location.href,
            timed_out: true,
          });
        }
      }, timeoutMs);

      const check = () => {
        if (document.readyState !== "complete") return;
        if (selector && !document.querySelector(selector)) return;
        if (!resolved) {
          resolved = true;
          clearTimeout(timer);
          observer.disconnect();
          resolve({ ready: true, url: window.location.href });
        }
      };

      if (document.readyState === "complete") check();

      // Use MutationObserver to detect DOM changes after load
      const observer = new MutationObserver(() => check());
      observer.observe(document.body || document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
      });

      window.addEventListener("load", check);
    });
  }

  // ── Selector Testing ─────────────────────────────────────

  function testSelector(selector) {
    try {
      const elements = document.querySelectorAll(selector);
      const found = elements.length > 0;
      const count = elements.length;
      let sampleHTML = null;
      if (found && elements[0]) {
        sampleHTML = sanitize(elements[0].outerHTML.substring(0, 500));
      }
      return { selector, found, count, sample_html: sampleHTML };
    } catch (e) {
      return { selector, found: false, count: 0, error: e.message };
    }
  }

  function testSelectors(selectors) {
    return selectors.map(s => {
      if (typeof s === "string") return testSelector(s);
      return testSelector(s.selector || s);
    });
  }

  // ── State Detection ──────────────────────────────────────

  function detectPageState(hints) {
    const results = [];
    for (const hint of hints) {
      let matched = false;
      let matchType = "";
      for (const check of hint.checks || hint.selectors || []) {
        const type = check.type;
        const value = check.value || check.selector;
        if (type === "element_present") {
          matched = document.querySelector(value) !== null;
          matchType = "element_present";
        } else if (type === "element_absent") {
          matched = document.querySelector(value) === null;
          matchType = "element_absent";
        } else if (type === "aria_present") {
          matched = document.querySelector('[role="' + value + '"]') !== null;
          matchType = "aria_present";
        } else if (type === "url_contains") {
          matched = window.location.href.includes(value);
          matchType = "url_contains";
        } else if (type === "url_matches") {
          try {
            matched = new RegExp(value).test(window.location.href);
            matchType = "url_matches";
          } catch (e) {
            matched = false;
          }
        }
        if (matched) break;
      }
      results.push({ state: hint.name || hint.id, matched, match_type: matchType });
    }
    return results;
  }

  // ── Message Handler ──────────────────────────────────────

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    // Support both sync and async responses
    function respond(data) {
      try { sendResponse(data); } catch (e) { /* channel closed */ }
    }

    if (message.action === "capture_snapshot") {
      respond(captureDOMSnapshot(message.options || {}));
      return false;
    }

    if (message.action === "test_selectors") {
      respond({ results: testSelectors(message.selectors || []) });
      return false;
    }

    if (message.action === "detect_state") {
      respond({ results: detectPageState(message.hints || []) });
      return false;
    }

    if (message.action === "wait_for_ready") {
      waitForReady(message.options || {}).then(data => {
        respond(data);
      }).catch(err => {
        respond({ ready: false, error: err.message });
      });
      return true; // async
    }

    if (message.action === "ping") {
      respond({ pong: true, url: window.location.href });
      return false;
    }

    return false;
  });

  console.log("[ANBM Bridge v2] content script loaded on", window.location.href);
})();
