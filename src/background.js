// Event page. It clips a tab on request (popup, right-click menu, shortcut)
// and, for the menu and the shortcut, copies or saves the result.
//
// The only access to pages is activeTab: Firefox grants it for the tab the
// user opened the popup on, right-clicked in, or pressed the shortcut on.
"use strict";

const Settings = globalThis.ExcerptSettings;
const FILES = ["vendor/Readability.js", "vendor/turndown.js", "content/markdown.js", "content/clip.js"];

/** Call one function of content/clip.js in a frame of a tab. */
async function call(tabId, frameId, method, ...args) {
  const results = await browser.scripting.executeScript({
    target: { tabId, frameIds: [frameId] },
    func: (name, list) => globalThis.__excerpt[name](...list),
    args: [method, args],
  });
  const first = results && results[0];
  if (!first || first.error) throw new Error(String((first && first.error && (first.error.message || first.error)) || "no result"));
  return first.result;
}

/** Inject the clipper into a frame and clip. Never throws: failures come back as { ok: false, error }. */
async function clipTab(tabId, frameId, request) {
  // about: pages, addons.mozilla.org, the PDF viewer, reader view: Firefox lets
  // no add-on in there, with or without activeTab. Depending on the page it
  // either refuses outright or answers with an empty result.
  try {
    const injected = await browser.scripting.executeScript({ target: { tabId, frameIds: [frameId] }, files: FILES });
    if (!injected || !injected[0]) return { ok: false, error: "blocked" };
    if (injected[0].error) return { ok: false, error: "failed", detail: String(injected[0].error.message || injected[0].error) };
  } catch (e) {
    return { ok: false, error: "blocked", detail: String((e && e.message) || e) };
  }
  try {
    const result = await call(tabId, frameId, "clip", request);
    return result ? { ...result, frameId } : { ok: false, error: "failed" };
  } catch (e) {
    return { ok: false, error: "failed", detail: String((e && e.message) || e) };
  }
}

// ------------------------------------------------------------------ counters

// One at a time, so two quick clips can not lose a count.
let counting = Promise.resolve();

function countClip() {
  counting = counting.then(async () => {
    const got = await browser.storage.local.get({ stats: { clips: 0 } });
    await browser.storage.local.set({ stats: { clips: ((got.stats && got.stats.clips) || 0) + 1 } });
  }).catch(() => {});
  return counting.then(() => ({ ok: true }));
}

// ------------------------------------------------- right-click menu, shortcut

/** Nothing can be shown inside this page: say it on the toolbar button instead. */
async function flag(title) {
  try {
    await browser.action.setBadgeBackgroundColor({ color: "#B3261E" });
    await browser.action.setBadgeText({ text: "!" });
    await browser.action.setTitle({ title });
    setTimeout(() => {
      browser.action.setBadgeText({ text: "" });
      browser.action.setTitle({ title: null });
    }, 2500);
  } catch {
    // The badge is a nicety only.
  }
}

async function say(tabId, frameId, message, ok) {
  try {
    await call(tabId, frameId, "toast", message, ok);
  } catch {
    if (!ok) flag("Excerpt: " + message);
  }
}

/** Save through a link in this (invisible) page. Only for pages that can not start a download themselves. */
function saveHere(fileName, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}

/**
 * Clip without the popup and do what the settings say: copy, or save a file.
 * mode: "auto" (selection if there is one, else the article), "article" or "selection".
 */
async function quickClip(tab, frameId, mode, fallbackText) {
  if (!tab || tab.id == null) return;
  const settings = await Settings.load();
  const request = { mode, settings, fallbackText };
  const clipped = (async () => {
    let result = await clipTab(tab.id, frameId, request);
    // A frame from another site is out of reach for activeTab: use the top page and the plain selected text.
    if (!result.ok && frameId !== 0) result = await clipTab(tab.id, 0, request);
    return result;
  })();

  let copied = false;
  if (settings.quickAction === "copy") {
    // Firefox lets this page write to the clipboard for about five seconds after
    // the click or shortcut. The write is started right away with a promise for
    // the text, so a long article that takes a while to convert still lands.
    try {
      const text = clipped.then((result) => {
        if (!result.ok) throw new Error(result.error);
        return result.text;
      });
      await navigator.clipboard.write([new ClipboardItem({ "text/plain": text })]);
      copied = true;
    } catch {
      copied = false;
    }
  }

  const result = await clipped;
  if (!result.ok) {
    if (result.error === "blocked") flag("Excerpt can't clip this page (Firefox blocks add-ons here)");
    else if (result.error === "empty") say(tab.id, 0, "Nothing to clip here", false);
    else if (result.error === "unsupported") flag("Excerpt can't clip this kind of document");
    else flag("Excerpt could not clip this page");
    return;
  }
  const at = result.frameId || 0;
  const amount = result.words === 1 ? "1 word" : result.words.toLocaleString("en-US") + " words";

  if (settings.quickAction === "save") {
    try {
      if (result.sandboxed) saveHere(result.fileName, result.text);
      else await call(tab.id, at, "download", result.fileName, result.text);
    } catch {
      say(tab.id, at, "Could not save the file", false);
      return;
    }
    say(tab.id, at, "Saved " + result.fileName, true);
  } else {
    if (!copied) copied = await call(tab.id, at, "copy", result.text).catch(() => false);
    if (!copied) {
      say(tab.id, at, "Could not copy. Use Copy in the Excerpt popup instead", false);
      return;
    }
    say(tab.id, at, "Copied " + amount + " as Markdown", true);
  }
  countClip();
}

function createMenus() {
  if (!browser.menus) return;
  browser.menus.removeAll().then(() => {
    browser.menus.create({ id: "clip-selection", title: "Clip selection as Markdown", contexts: ["selection"] });
    browser.menus.create({ id: "clip-page", title: "Clip page as Markdown", contexts: ["page", "frame"] });
  }, () => {});
}

browser.runtime.onInstalled.addListener(createMenus);
browser.runtime.onStartup.addListener(createMenus);

if (browser.menus) {
  browser.menus.onClicked.addListener((info, tab) => {
    if (info.menuItemId === "clip-selection") quickClip(tab, info.frameId || 0, "selection", info.selectionText || "");
    else if (info.menuItemId === "clip-page") quickClip(tab, 0, "article", "");
  });
}

if (browser.commands) {
  browser.commands.onCommand.addListener(async (name, tab) => {
    if (name !== "clip") return;
    const target = tab || (await browser.tabs.query({ active: true, currentWindow: true }))[0];
    quickClip(target, 0, "auto", "");
  });
}

// --------------------------------------------------------------------- popup

browser.runtime.onMessage.addListener((msg, sender) => {
  if (!msg || sender.id !== browser.runtime.id) return undefined;
  switch (msg.type) {
    case "excerpt:clip": // an explicit tabId: the popup may run in a tab of its own (tests, screenshots)
      if (!Number.isInteger(msg.tabId)) return Promise.resolve({ ok: false, error: "blocked" });
      return Settings.load().then((settings) => clipTab(msg.tabId, 0, { mode: String(msg.mode || "auto"), settings }));
    case "excerpt:done":
      return countClip();
    default:
      return undefined;
  }
});
