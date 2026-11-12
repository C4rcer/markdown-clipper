import { wireSupportLinks, maybeShowMilestone } from "../shared/support.js";

const Settings = globalThis.ExcerptSettings;
const $ = (id) => document.getElementById(id);

// ?tab=<id> drives the popup from a normal tab (the E2E and the listing screenshots).
const params = new URLSearchParams(location.search);
const forcedTab = params.has("tab") ? Number(params.get("tab")) : null;

const MODES = ["article", "page", "selection"];
let tabId = forcedTab;
let mode = "auto"; // what the preview shows; "auto" until the first clip comes back
let fileName = "";
let ready = false; // there is Markdown in the preview
let asking = 0; // newest request wins when the user switches quickly
let toastTimer = 0;

const countWords = (text) => (text.trim().match(/\S+/g) || []).length;

function toast(message, bad) {
  const t = $("toast");
  t.textContent = message;
  t.classList.toggle("bad", !!bad);
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 1800);
}

function showCount() {
  const text = $("preview").value;
  const words = countWords(text);
  $("count").textContent = ready
    ? (words === 1 ? "1 word" : words.toLocaleString("en-US") + " words") + " \u00B7 " + text.length.toLocaleString("en-US") + " characters"
    : "";
}

function render(hasSelection) {
  for (const b of $("mode").children) {
    const on = b.dataset.mode === mode;
    b.setAttribute("aria-checked", String(on));
    b.tabIndex = on || (mode === "auto" && b.dataset.mode === "article") ? 0 : -1;
    if (b.dataset.mode === "selection" && hasSelection !== undefined) {
      b.disabled = !hasSelection;
      b.title = hasSelection ? "Only the text you selected on the page" : "Select some text on the page first";
    }
  }
  $("preview").readOnly = !ready;
  $("copy").disabled = !ready;
  $("save").disabled = !ready;
  $("file").textContent = ready ? fileName : "";
  showCount();
}

function fail(error, hasSelection) {
  ready = false;
  $("preview").value = "";
  $("note").hidden = true;
  const messages = {
    blocked: "Firefox doesn't let add-ons read this page. Open a regular website and try again.",
    unsupported: "Excerpt can't clip this kind of document. It works on regular web pages.",
    empty: "There is nothing to clip here.",
    "no-selection": "Nothing is selected on the page. Select some text first, or clip the article.",
  };
  $("error").textContent = messages[error] || "This page could not be clipped. Reload it and try again.";
  $("error").hidden = false;
  render(hasSelection);
}

async function clip(want) {
  const mine = ++asking;
  $("error").hidden = true;
  let result;
  try {
    if (tabId == null) {
      const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
      tabId = tab ? tab.id : null;
    }
    result = await browser.runtime.sendMessage({ type: "excerpt:clip", tabId, mode: want });
  } catch {
    result = { ok: false, error: "failed" };
  }
  if (mine !== asking) return;
  if (!result || !result.ok) {
    if (result && MODES.includes(result.mode)) mode = result.mode;
    else if (MODES.includes(want)) mode = want;
    fail(result && result.error, result ? result.hasSelection : undefined);
    return;
  }
  mode = result.mode;
  fileName = result.fileName;
  ready = true;
  $("preview").value = result.text;
  $("preview").scrollTop = 0;
  $("note").textContent = "Nothing here reads like an article, so this is the whole page.";
  $("note").hidden = !result.fallback;
  render(result.hasSelection);
}

// ------------------------------------------------------------------- actions

function flash(button, label) {
  const old = button.dataset.label || button.textContent;
  button.dataset.label = old;
  button.textContent = label;
  clearTimeout(Number(button.dataset.timer));
  button.dataset.timer = String(setTimeout(() => { button.textContent = old; }, 1400));
}

function done() {
  browser.runtime.sendMessage({ type: "excerpt:done" }).catch(() => {});
}

async function copy() {
  const text = $("preview").value;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    toast("Could not copy", true);
    return;
  }
  flash($("copy"), "\u2713 Copied");
  toast("\u2713 Copied as Markdown");
  done();
}

function save() {
  const url = URL.createObjectURL(new Blob([$("preview").value], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  flash($("save"), "\u2713 Saved");
  toast("\u2713 Saved " + fileName);
  done();
}

// -------------------------------------------------------------------- wiring

wireSupportLinks();

$("btnOptions").addEventListener("click", () => {
  browser.runtime.openOptionsPage();
  if (forcedTab == null) window.close();
});

$("mode").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-mode]");
  if (b && !b.disabled && b.dataset.mode !== mode) clip(b.dataset.mode);
});
$("mode").addEventListener("keydown", (e) => {
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
  if (!step) return;
  e.preventDefault();
  const usable = Array.from($("mode").children).filter((b) => !b.disabled);
  const at = usable.findIndex((b) => b.dataset.mode === mode);
  const next = usable[(Math.max(at, 0) + step + usable.length) % usable.length];
  next.focus();
  next.click();
});

$("frontMatter").addEventListener("change", async (e) => {
  await Settings.save({ frontMatter: e.target.checked });
  clip(mode);
});

$("preview").addEventListener("input", showCount);
$("copy").addEventListener("click", copy);
$("save").addEventListener("click", save);

if (browser.commands) {
  browser.commands.getAll().then((all) => {
    const cmd = all.find((c) => c.name === "clip");
    if (cmd && cmd.shortcut) {
      $("shortcut").textContent = cmd.shortcut;
      $("hint").hidden = false;
    }
  }, () => {});
}

(async () => {
  const settings = await Settings.load();
  $("frontMatter").checked = settings.frontMatter;
  render();
  await clip("auto");
  if (ready) $("copy").focus(); // open the popup, press Enter: copied
  let clips = 0;
  try {
    const got = await browser.storage.local.get({ stats: { clips: 0 } });
    clips = (got.stats && got.stats.clips) || 0;
  } catch {
    clips = 0;
  }
  maybeShowMilestone($("supportCard"), clips, [25, 250], (m) =>
    `You've clipped ${m} pages with Excerpt. It's free and ad-free; if it saves you time, a coffee keeps it maintained.`);
})();
