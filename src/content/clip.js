// Injected on demand (toolbar button, right-click menu or shortcut), together
// with vendor/Readability.js, vendor/turndown.js and content/markdown.js.
// It reads the page and hands back Markdown. It never changes the page: all
// the work happens on a detached copy that loads nothing and runs nothing.
"use strict";

(() => {
  if (globalThis.__excerpt) return;
  const Markdown = globalThis.__excerptMarkdown;
  const HIDDEN = "data-excerpt-hidden";

  // ----------------------------------------------------------------- page data

  function pageMeta() {
    const meta = (selector) => {
      const el = document.querySelector(selector);
      return el ? (el.getAttribute("content") || "").trim() : "";
    };
    return {
      title: (document.title || "").replace(/\s+/g, " ").trim() || meta('meta[property="og:title"]') || location.hostname,
      url: location.href,
      author: meta('meta[name="author"]'),
      site: meta('meta[property="og:site_name"]') || location.hostname,
      description: meta('meta[name="description"]') || meta('meta[property="og:description"]'),
      published: meta('meta[property="article:published_time"]') || meta('meta[name="date"]'),
    };
  }

  /**
   * Page titles are often "Post title | Site name". When the page has a main
   * heading that is the title minus such an extra, that heading is the better
   * name for the clip and for the file.
   */
  function refineTitle(title) {
    const lower = title.toLowerCase();
    const found = [];
    for (const h of document.querySelectorAll("h1")) {
      const text = h.textContent.replace(/\s+/g, " ").trim();
      if (text.length >= 8 && text.length < title.length && lower.includes(text.toLowerCase())) found.push({ h, text });
    }
    if (found.length < 2) return found.length ? found[0].text : title;
    // Several candidates (a site name in the header is often an <h1> too): the one in the main content wins.
    const main = found.filter((f) => f.h.closest("article, main, [role=main]"));
    const pool = main.length ? main : found;
    return (pool.find((f) => lower.startsWith(f.text.toLowerCase())) || pool[0]).text;
  }

  /** The user's selection, or null when nothing (or only white space) is selected. */
  function currentSelection() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    const text = sel.toString();
    return text.trim() ? { sel, text } : null;
  }

  // ---------------------------------------------------- the copy we work on

  /** No box on screen: hidden, unless it is display: contents (which still shows its children). */
  const isHidden = (el) => typeof el.checkVisibility === "function" && !el.checkVisibility()
    && getComputedStyle(el).display !== "contents";

  // Web components keep their content in a shadow tree. Add-ons may look into closed ones too.
  const shadowOf = (el) => el.openOrClosedShadowRoot || el.shadowRoot || null;

  /**
   * Walk a part of the real page and its copy side by side (they have the same
   * shape). The copy has no layout and no shadow trees of its own, so both
   * answers come from the real element at the same position:
   *   - job.flag: mark in the copy what the reader can not see,
   *   - job.twins: remember which copy belongs to which real node (for selections),
   *   - returns the shadow trees of visible elements, as [shadow tree, its host in the copy].
   */
  function pairUp(realRoot, twinRoot, copy, job) {
    const what = job.twins ? NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT : NodeFilter.SHOW_ELEMENT;
    const real = document.createTreeWalker(realRoot, what);
    const twin = copy.createTreeWalker(twinRoot, what);
    const hosts = [];
    for (let a = real.nextNode(), b = twin.nextNode(); a && b; a = real.nextNode(), b = twin.nextNode()) {
      if (a.nodeName !== b.nodeName) break; // never seen; stop rather than pair the wrong nodes
      if (job.twins) job.twins.set(a, b);
      if (a.nodeType !== 1) continue;
      const shadow = shadowOf(a);
      if (!shadow && !job.flag) continue;
      if (isHidden(a)) {
        if (job.flag) b.setAttribute(HIDDEN, "");
      } else if (shadow) {
        hosts.push([shadow, b]);
      }
    }
    return hosts;
  }

  /**
   * Give a host in the copy what its shadow tree shows on the real page: the
   * tree itself, with each <slot> replaced by the host's own children that the
   * browser puts there (or by the slot's fallback when there are none).
   */
  function fillShadow(shadow, host, copy, job, depth) {
    job.roots.push(shadow);
    const tree = copy.createDocumentFragment();
    for (const child of shadow.childNodes) tree.append(copy.importNode(child, true));
    // Inside a component everything invisible is flagged: its markup only makes sense as rendered.
    const inner = depth < 10 ? pairUp(shadow, tree, copy, { ...job, flag: true }) : [];
    for (const slot of tree.querySelectorAll("slot")) {
      const name = slot.getAttribute("name") || "";
      const given = Array.from(host.childNodes).filter((n) => (
        n.nodeType === 1 ? (n.getAttribute("slot") || "") === name : n.nodeType === 3 && name === ""));
      slot.replaceWith(...(given.length ? given : slot.childNodes));
    }
    for (const [innerShadow, innerHost] of inner) fillShadow(innerShadow, innerHost, copy, job, depth + 1);
    host.replaceChildren(tree);
  }

  /**
   * A detached copy of the whole page, shadow trees included.
   * flag: also mark what is hidden on the real page. twins: also keep the real-node-to-copy map.
   */
  function copyPage(flag, twins) {
    const copy = document.cloneNode(true);
    const job = { flag, twins: twins ? new WeakMap() : null, roots: [] };
    if (job.twins) {
      job.twins.set(document, copy);
      job.twins.set(document.documentElement, copy.documentElement);
      job.twins.set(document.body, copy.body);
    }
    if (copy.body) {
      for (const [shadow, host] of pairUp(document.body, copy.body, copy, job)) fillShadow(shadow, host, copy, job, 0);
    }
    return { copy, twins: job.twins, roots: job.roots };
  }

  // ----------------------------------------------------------------- selection

  /** The selection's ranges. A selection that runs into or out of a component only shows up whole as a "composed" range. */
  function rangesOf(sel, roots) {
    if (sel.rangeCount === 1 && typeof sel.getComposedRanges === "function") {
      try {
        const composed = sel.getComposedRanges({ shadowRoots: roots });
        if (composed.length) return Array.from(composed);
      } catch {
        // Fall through to the plain ranges.
      }
    }
    const ranges = [];
    for (let i = 0; i < sel.rangeCount; i++) ranges.push(sel.getRangeAt(i));
    return ranges;
  }

  /** The same range, in the copy. */
  function twinRange(range, copy, twins) {
    const start = twins.get(range.startContainer);
    const end = twins.get(range.endContainer);
    if (!start || !end) return null;
    try {
      const twin = copy.createRange();
      twin.setStart(start, range.startOffset);
      twin.setEnd(end, range.endOffset);
      return twin.collapsed ? null : twin;
    } catch {
      return null;
    }
  }

  /**
   * What a range covers, as elements. A range cut out of the middle of a code
   * block, a list or a table loses the tags that made it one, so those are put
   * back around it. A few words out of a paragraph or a list item stay plain.
   */
  function rangeContents(range) {
    let anchor = range.commonAncestorContainer;
    if (anchor.nodeType !== 1) anchor = anchor.parentElement;
    const chain = [];
    const pre = anchor && anchor.closest("pre");
    if (pre) {
      // Up to the code block, and one more for a wrapper that names the language.
      for (let el = anchor; el; el = el.parentElement) {
        chain.push(el);
        if (el === pre) break;
      }
      const wrapper = (el) => !!el && (/^(DIV|FIGURE)$/.test(el.nodeName) || el.nodeName.includes("-"));
      if (wrapper(pre.parentElement)) {
        chain.push(pre.parentElement);
        if (wrapper(pre.parentElement.parentElement)) chain.push(pre.parentElement.parentElement);
      }
    } else if (anchor && /^(UL|OL)$/.test(anchor.nodeName)) {
      chain.push(anchor);
    } else if (anchor && /^(TABLE|THEAD|TBODY|TFOOT|TR)$/.test(anchor.nodeName)) {
      for (let el = anchor; el; el = el.parentElement) {
        chain.push(el);
        if (el.nodeName === "TABLE") break;
      }
    } else if (anchor && anchor.closest("code")) {
      chain.push(anchor.closest("code"));
    }
    let node = range.cloneContents();
    let list = null;
    for (const el of chain) {
      const shell = el.cloneNode(false);
      shell.append(node);
      node = shell;
      if (el === anchor && el.nodeName === "OL") list = shell;
    }
    if (list) {
      // Keep the numbers the reader saw: a selection that starts at item 3 starts at "3.".
      let item = range.startContainer === anchor ? anchor.childNodes[range.startOffset] : range.startContainer;
      while (item && item.parentNode !== anchor) item = item.parentNode;
      while (item && item.nodeType !== 1) item = item.nextSibling; // white space between two items
      const index = item ? Array.prototype.indexOf.call(anchor.children, item) : -1;
      const first = parseInt(anchor.getAttribute("start"), 10);
      if (index > 0) list.setAttribute("start", String((Number.isFinite(first) ? first : 1) + index));
    }
    return node;
  }

  /** Dragging across table cells makes Firefox select each cell as its own range. Put them back into one table. */
  function cellRangesAsTable(ranges, copy) {
    const cells = [];
    for (const range of ranges) {
      const row = range.startContainer;
      if (row !== range.endContainer || row.nodeName !== "TR" || range.endOffset - range.startOffset !== 1) return null;
      const cell = row.childNodes[range.startOffset];
      if (!cell || !/^(TD|TH)$/.test(cell.nodeName)) return null;
      cells.push(cell);
    }
    const table = cells[0].closest("table");
    if (!table || cells.some((cell) => cell.closest("table") !== table)) return null;
    const out = copy.createElement("table");
    const body = out.appendChild(copy.createElement("tbody"));
    let lastRow = null;
    let tr = null;
    for (const cell of cells) {
      if (cell.parentNode !== lastRow) {
        lastRow = cell.parentNode;
        tr = body.appendChild(copy.createElement("tr"));
      }
      tr.append(cell.cloneNode(true));
    }
    return out;
  }

  /** The selected part of the page as one element in the copy, or null when the copy can not reach it (a text box). */
  function selectionRoot(selection) {
    const { copy, twins, roots } = copyPage(true, true);
    const ranges = rangesOf(selection.sel, roots).map((range) => twinRange(range, copy, twins));
    if (!ranges.length || ranges.some((range) => !range)) return null;
    const box = copy.createElement("div");
    const table = ranges.length > 1 ? cellRangesAsTable(ranges, copy) : null;
    if (table) box.append(table);
    else for (const range of ranges) box.append(rangeContents(range));
    return box;
  }

  const sameText = (a, b) => a.replace(/\s+/g, " ").trim().toLowerCase() === b.replace(/\s+/g, " ").trim().toLowerCase();

  /** The page title as an <h1>, so it goes through the same rules (heading style, escaping) as the rest. */
  function headingFor(title) {
    const doc = document.implementation.createHTMLDocument("");
    const box = doc.createElement("div");
    box.appendChild(doc.createElement("h1")).textContent = title;
    return box;
  }

  // ---------------------------------------------------------------------- clip

  /**
   * request: { mode: "auto" | "article" | "page" | "selection", settings, fallbackText }
   * Returns { ok, mode, fallback, hasSelection, title, fileName, text, words } or { ok: false, error }.
   */
  function clip(request) {
    const settings = request.settings;
    if (!document.body || !(document instanceof HTMLDocument)) return { ok: false, error: "unsupported" };
    const selection = currentSelection();
    const plain = String(request.fallbackText || "").trim();
    let mode = request.mode;
    if (mode === "auto") mode = selection ? "selection" : "article";
    if (mode === "selection" && !selection && !plain) return { ok: false, error: "no-selection", hasSelection: false };

    const meta = pageMeta();
    let title = refineTitle(meta.title);
    let fallback = false;
    let body = "";

    if (mode === "selection") {
      const root = selection && selectionRoot(selection);
      body = root ? Markdown.toMarkdown(root, settings) : (selection ? selection.text : plain).trim();
    }

    if (mode === "article") {
      // The same rules as Firefox Reader View decide what the article is. Like Reader View it does not
      // look at style sheets, so text that the page keeps folded away (an answer in a FAQ) is included.
      let article = null;
      try {
        const { copy } = copyPage(false, false);
        Markdown.prepare(copy);
        // keepClasses: code blocks name their language in a class. serializer: hand back the elements, not HTML text.
        article = new Readability(copy, { keepClasses: true, serializer: (el) => el }).parse();
      } catch {
        article = null;
      }
      if (article && article.content && (article.textContent || "").trim()) {
        const root = article.content;
        title = refineTitle((article.title || "").replace(/\s+/g, " ").trim() || title);
        meta.author = (article.byline || "").replace(/\s+/g, " ").trim() || meta.author;
        meta.site = article.siteName || meta.site;
        meta.description = meta.description || article.excerpt || "";
        meta.published = article.publishedTime || meta.published;
        // Readability hands the title over separately; drop a heading that only repeats it.
        const h1 = root.querySelector("h1");
        if (h1 && sameText(h1.textContent, title)) h1.remove();
        body = Markdown.toMarkdown(root, settings);
        if (settings.titleHeading && body) body = Markdown.toMarkdown(headingFor(title), settings) + "\n\n" + body;
      } else {
        mode = "page"; // nothing that reads like an article here
        fallback = true;
      }
    }

    if (mode === "page") {
      // Everything the reader can see, nothing they can not.
      const { copy } = copyPage(true, false);
      const hasH1 = !!copy.body.querySelector("h1:not([" + HIDDEN + "])");
      body = Markdown.toMarkdown(copy.body, settings);
      if (settings.titleHeading && body && !hasH1) body = Markdown.toMarkdown(headingFor(title), settings) + "\n\n" + body;
    }

    if (!body) return { ok: false, error: "empty", mode, hasSelection: !!selection };

    let text = body + "\n";
    if (settings.frontMatter && settings.frontMatterTemplate.trim()) {
      const values = { ...meta, title, ...Markdown.dateParts(new Date()) };
      text = Markdown.renderTemplate(settings.frontMatterTemplate, values) + "\n\n" + text;
    }
    return {
      ok: true,
      mode,
      fallback,
      hasSelection: !!selection,
      title,
      fileName: Markdown.fileName(title, location.hostname),
      text,
      words: Markdown.countWords(body),
      // A page served with "Content-Security-Policy: sandbox" can not start downloads; the background saves instead.
      sandboxed: window.origin === "null",
    };
  }

  // ------------------------------------------- after a right-click or shortcut

  /** Small confirmation in the corner of the page. Gone after two seconds. */
  function toast(message, ok) {
    for (const old of document.querySelectorAll("[data-excerpt-toast]")) old.remove();
    const el = document.createElement("div");
    el.setAttribute("data-excerpt-toast", "");
    el.setAttribute("role", "status");
    // Styled through the CSSOM only: a strict Content-Security-Policy blocks <style>, not this.
    el.style.cssText = [
      "all: initial", "position: fixed", "inset: auto 16px 16px auto", "z-index: 2147483647", "display: block",
      "box-sizing: border-box", "max-width: min(420px, calc(100vw - 32px))", "margin: 0", "padding: 9px 14px",
      "border: 0", "border-radius: 10px", "background: #16161a", "color: " + (ok ? "#6ee7a8" : "#ffb4ab"),
      "font: 600 13px/1.35 system-ui, sans-serif", "box-shadow: 0 6px 20px rgba(0, 0, 0, .35)",
      "overflow: hidden", "text-overflow: ellipsis", "white-space: nowrap", "pointer-events: none",
    ].join("; ");
    el.textContent = (ok ? "\u2713 " : "") + message;
    (document.body || document.documentElement).append(el);
    try {
      el.popover = "manual"; // top layer: above any z-index and any open dialog
      el.showPopover();
    } catch {
      // Still visible as a fixed box.
    }
    setTimeout(() => el.remove(), 2200);
    return true;
  }

  /** Save text as a file through the page, like a click on a download link. */
  function download(fileName, text) {
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    a.style.cssText = "display: none";
    (document.body || document.documentElement).append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    return true;
  }

  /** Second try for the clipboard when the background was refused (see background.js). */
  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return false;
    }
  }

  globalThis.__excerpt = { clip, toast, download, copy };
})();
