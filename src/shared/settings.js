// Settings shared by the background, the popup and the options page (classic
// script: it puts one object on the global). Everything lives in
// browser.storage.local under "settings".
"use strict";

(() => {
  const DEFAULT_TEMPLATE = [
    "---",
    'title: "{title}"',
    "source: {url}",
    "clipped: {date}",
    "---",
  ].join("\n");

  // What can go into the front matter template, in the order the options page lists it.
  const PLACEHOLDERS = [
    ["title", "Page or article title"],
    ["url", "Address of the page"],
    ["date", "Today's date, like 2026-11-10"],
    ["time", "Time of the clip, like 14:05"],
    ["datetime", "Date and time, like 2026-11-10T14:05:09"],
    ["author", "Author, when the page names one"],
    ["site", "Site name, or the host name"],
    ["description", "The page's own summary, or its first paragraph"],
    ["published", "Publication date, when the page gives one"],
  ];

  const DEFAULTS = Object.freeze({
    headingStyle: "atx", // "atx": # Heading, "setext": underlined (levels 1 and 2 only)
    bullet: "-", // "-", "*" or "+"
    linkStyle: "inline", // "inline": [text](url), "reference": [text][1] with the urls at the end
    images: true,
    titleHeading: true, // start a page clip with "# Title"
    frontMatter: false,
    frontMatterTemplate: DEFAULT_TEMPLATE,
    quickAction: "copy", // what the right-click menu and the shortcut do: "copy" or "save"
  });

  const CHOICES = {
    headingStyle: ["atx", "setext"],
    bullet: ["-", "*", "+"],
    linkStyle: ["inline", "reference"],
    quickAction: ["copy", "save"],
  };
  const TEMPLATE_MAX = 4000;

  /** Stored value (anything) to a complete, valid settings object. */
  function normalize(raw) {
    const src = raw && typeof raw === "object" ? raw : {};
    const out = { ...DEFAULTS };
    for (const [key, allowed] of Object.entries(CHOICES)) {
      if (allowed.includes(src[key])) out[key] = src[key];
    }
    for (const key of ["images", "titleHeading", "frontMatter"]) {
      if (typeof src[key] === "boolean") out[key] = src[key];
    }
    if (typeof src.frontMatterTemplate === "string") {
      out.frontMatterTemplate = src.frontMatterTemplate.slice(0, TEMPLATE_MAX);
    }
    return out;
  }

  async function load() {
    try {
      const got = await browser.storage.local.get("settings");
      return normalize(got.settings);
    } catch {
      return { ...DEFAULTS };
    }
  }

  /** Merge a change into the stored settings. Returns the new settings. */
  async function save(patch) {
    const next = normalize({ ...(await load()), ...patch });
    await browser.storage.local.set({ settings: next });
    return next;
  }

  globalThis.ExcerptSettings = { DEFAULTS, DEFAULT_TEMPLATE, PLACEHOLDERS, TEMPLATE_MAX, normalize, load, save };
})();
