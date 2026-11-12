// HTML to Markdown, front matter and file names. Runs in the page's content
// script next to vendor/turndown.js (which provides TurndownService).
//
// Everything here works on a detached copy of the page (see clip.js): nothing
// is loaded, nothing in the live page is touched.
"use strict";

(() => {
  if (globalThis.__excerptMarkdown) return;

  // ------------------------------------------------------------- tidy the copy

  const JUNK = [
    "script", "style", "noscript", "template", "link", "meta", "title", "head", "object", "embed", "canvas", "svg",
    "audio", "video", "source", "track", "map", "input", "select", "textarea", "button", "datalist", "dialog:not([open])",
    "[data-excerpt-toast]", "[data-excerpt-hidden]",
    ".mw-editsection", // the "[edit]" next to every heading on Wikipedia and other MediaWiki sites
  ].join(",");

  const BLOCKS = "pre, p, table, ul, ol, h1, h2, h3, h4, h5, h6, blockquote";

  // Line-number columns that syntax highlighters (Rouge, Pygments, highlight.js) put next to the code.
  const GUTTERS = "td.gutter, td.rouge-gutter, td.linenos, td.hljs-ln-numbers, pre.lineno, .linenodiv, span.lineno, span.linenos";

  // Embedded players worth keeping as a link (the same hosts Firefox Reader View keeps).
  const VIDEO_HOSTS = /^https?:\/\/(www\.)?((dailymotion|youtube|youtube-nocookie|player\.vimeo|v\.qq|bilibili|live\.bilibili)\.com|(archive|upload\.wikimedia)\.org|player\.twitch\.tv)\//i;

  const LINK_SCHEMES = /^(https?|mailto|tel|ftp|file):$/i;

  function absolute(raw, base) {
    try {
      return new URL(String(raw).trim(), base);
    } catch {
      return null;
    }
  }

  /** The largest candidate of a srcset (they are listed small to large by convention). */
  function fromSrcset(srcset) {
    if (!srcset) return "";
    const last = srcset.split(/,\s+/).map((s) => s.trim()).filter(Boolean).pop();
    return last ? last.split(/\s+/)[0] : "";
  }

  function tidyImages(root, base, keep) {
    if (!keep) {
      // A link that is nothing but a picture keeps the picture's description as its text.
      for (const a of root.querySelectorAll("a[href]")) {
        if (a.textContent.trim()) continue;
        const img = a.querySelector("img[alt]");
        const alt = img ? img.getAttribute("alt").replace(/\s+/g, " ").trim() : "";
        if (alt) a.textContent = alt;
      }
      for (const fig of root.querySelectorAll("figure")) {
        if (fig.querySelector("img, picture") && !fig.querySelector("pre, table, blockquote")) fig.remove();
      }
      for (const el of root.querySelectorAll("img, picture")) el.remove();
      return;
    }
    for (const img of root.querySelectorAll("img")) {
      let src = img.getAttribute("src") || "";
      if (!src || /^data:/i.test(src)) {
        // Lazy-loaded image that has not been shown yet: the real address sits in another attribute.
        const picture = img.closest("picture");
        const source = picture && picture.querySelector("source[srcset]");
        src = img.getAttribute("data-src") || img.getAttribute("data-original") || img.getAttribute("data-lazy-src")
          || fromSrcset(img.getAttribute("srcset") || img.getAttribute("data-srcset"))
          || fromSrcset(source && source.getAttribute("srcset")) || "";
      }
      const url = src && !/^data:/i.test(src) ? absolute(src, base) : null;
      const tiny = Number(img.getAttribute("width")) === 1 && Number(img.getAttribute("height")) === 1; // tracking pixel
      if (!url || !/^https?:$/i.test(url.protocol) || tiny) {
        img.remove();
        continue;
      }
      img.setAttribute("src", url.href);
    }
  }

  function tidyLinks(root, base) {
    for (const a of root.querySelectorAll("a[href]")) {
      const url = absolute(a.getAttribute("href"), base);
      if (url && LINK_SCHEMES.test(url.protocol)) a.setAttribute("href", url.href);
      else a.removeAttribute("href"); // javascript:, data: and friends: keep the words, drop the link
    }
    for (const frame of root.querySelectorAll("iframe")) {
      const url = absolute(frame.getAttribute("src") || "", base);
      if (url && VIDEO_HOSTS.test(url.href)) frame.setAttribute("src", url.href);
      else frame.remove();
    }
  }

  function tidyHeadings(root) {
    const page = String(root.ownerDocument.documentURI || "").split("#")[0];
    for (const h of root.querySelectorAll("h1, h2, h3, h4, h5, h6")) {
      // A heading that is a link to itself (documentation sites do this) is just a heading.
      for (const a of h.querySelectorAll("a[href]")) {
        const url = absolute(a.getAttribute("href"), root.ownerDocument.baseURI);
        if (url && url.hash && url.href.split("#")[0] === page && a.textContent.trim().length > 1) a.replaceWith(...a.childNodes);
      }
      // "#" or pilcrow links that sites add next to a heading so it can be linked to.
      for (const a of h.querySelectorAll("a")) {
        const text = a.textContent.trim();
        const named = /anchor|permalink|header-?link|hash-?link/i.test(a.getAttribute("class") || "");
        if (a.querySelector("img")) continue;
        if (text === "" || /^[#\u00B6\u00A7\u{1F517}]$/u.test(text) || (named && text.length <= 1)) a.remove();
      }
    }
  }

  function tidyLists(root) {
    // <ul><li>a</li><ul>...</ul></ul> is not valid HTML but common: the inner list belongs to the item before it.
    for (const list of root.querySelectorAll("ul > ul, ul > ol, ol > ul, ol > ol")) {
      const prev = list.previousElementSibling;
      if (prev && prev.nodeName === "LI") prev.append(list);
    }
  }

  /**
   * Task lists: swap each checkbox in a list item for a marker character that
   * later becomes "[x]" or "[ ]". Done on the copy before anything else looks
   * at it, because Readability throws form controls away.
   */
  function keepTaskBoxes(root) {
    for (const input of root.querySelectorAll("li input[type=checkbox]")) {
      input.replaceWith(input.checked ? TASK_DONE : TASK_OPEN);
    }
  }

  function languageHint(el, loose) {
    if (!el || el.nodeType !== 1) return "";
    for (const name of ["data-lang", "data-language", "data-code-language"]) {
      const v = el.getAttribute(name);
      if (v) return v;
    }
    if (el.nodeName === "PRE" && el.getAttribute("lang")) return el.getAttribute("lang");
    const cls = el.getAttribute("class") || "";
    let m = cls.match(/(?:^|\s)language-(\S+)/i);
    if (m) return m[1];
    m = cls.match(/(?:^|\s)highlight-(?:source|text)-([a-z0-9+#]+)/i); // GitHub
    if (m) return m[1];
    m = cls.match(/\bbrush:\s*([^\s;]+)/i); // SyntaxHighlighter, old MDN
    if (m) return m[1];
    m = cls.match(/(?:^|\s)highlight-([a-z0-9+#]+)(?:\s|$)/i); // Sphinx
    if (m) return m[1];
    if (loose) {
      m = cls.match(/(?:^|\s)lang-(\S+)/i) || cls.match(/(?:^|\s)sourceCode\s+(\S+)/); // prettify, pandoc
      if (m) return m[1];
    }
    return "";
  }

  function detectLanguage(pre) {
    const parent = pre.parentElement;
    const candidates = [
      [pre.querySelector("code"), true], [pre, true], [parent, false], [parent && parent.parentElement, false],
    ];
    for (const [el, loose] of candidates) {
      const lang = languageHint(el, loose).toLowerCase();
      if (/^[a-z0-9+#._-]{1,24}$/.test(lang) && !/^(none|nohighlight|no-highlight|default|source)$/.test(lang)) return lang;
    }
    return "";
  }

  function tidyCode(root) {
    for (const el of root.querySelectorAll(GUTTERS)) el.remove();
    for (const pre of root.querySelectorAll("pre")) {
      if (pre.parentElement && pre.parentElement.closest("pre")) continue;
      for (const br of pre.querySelectorAll("br")) br.replaceWith("\n");
      const lang = detectLanguage(pre);
      if (lang) pre.setAttribute("data-excerpt-lang", lang);
    }
  }

  /**
   * Copy buttons, language labels and "run this" links that code widgets put
   * next to a code block: a short neighbour of the block that holds a button.
   */
  function dropCodeChrome(root) {
    for (const pre of root.querySelectorAll("pre")) {
      if (!pre.parentElement) continue;
      for (const el of Array.from(pre.parentElement.children)) {
        if (el === pre || el.matches(BLOCKS) || el.querySelector(BLOCKS)) continue;
        if (el.querySelector("button, [role=button]") && el.textContent.trim().length <= 60) el.remove();
      }
    }
  }

  /**
   * First pass over a fresh copy of the page (or a part of it), before anything
   * else reads it: Readability, for one, throws form controls away and counts
   * links against a block.
   */
  function prepare(root) {
    for (const el of root.querySelectorAll("[data-excerpt-hidden]")) el.remove();
    keepTaskBoxes(root);
    dropCodeChrome(root);
  }

  function tidy(root, settings) {
    const base = root.ownerDocument.baseURI;
    prepare(root);
    for (const el of root.querySelectorAll(JUNK)) el.remove();
    tidyHeadings(root);
    tidyLists(root);
    tidyCode(root);
    tidyImages(root, base, settings.images);
    tidyLinks(root, base);
  }

  // ------------------------------------------------------------------ Turndown

  // Markers that table cells and rows leave in the text so the table rule can
  // put the grid together. Unicode noncharacters: no page contains them.
  const CELL = "\uFDD0";
  const CELL_END = "\uFDD1";
  const ROW = "\uFDD2";
  const ROW_END = "\uFDD3";
  const SEP = "\uFDD4";
  const CAPTION = "\uFDD5";
  const CAPTION_END = "\uFDD6";
  const MARKERS = /[\uFDD0-\uFDD6]/g;
  const TASK_DONE = "\uFDD7";
  const TASK_OPEN = "\uFDD8";
  const ROW_RE = /\uFDD2(\d)\uFDD4([\s\S]*?)\uFDD3/g;
  const CELL_RE = /\uFDD0(\d+),(\d+),(\d)\uFDD4([\s\S]*?)\uFDD1/g;
  const CAPTION_RE = /\uFDD5([\s\S]*?)\uFDD6/;

  const span = (node, name) => Math.min(Math.max(parseInt(node.getAttribute(name), 10) || 1, 1), 100);

  /** Characters that would end a (url) early are percent-encoded: every Markdown reader agrees on those. */
  const destination = (url) => url.replace(/[()<>\s]/g, (ch) => "%" + ch.charCodeAt(0).toString(16).toUpperCase().padStart(2, "0"));

  function makeService(settings) {
    const service = new TurndownService({
      headingStyle: settings.headingStyle === "setext" ? "setext" : "atx",
      hr: "---",
      bulletListMarker: settings.bullet,
      codeBlockStyle: "fenced",
      emDelimiter: "*",
      strongDelimiter: "**",
      br: "  ",
    });

    // ---- headings: one line, never empty
    service.addRule("heading", {
      filter: ["h1", "h2", "h3", "h4", "h5", "h6"],
      replacement(content, node, options) {
        const text = content.replace(/\s*\n\s*/g, " ").trim();
        if (!text) return "";
        const level = Number(node.nodeName.charAt(1));
        if (options.headingStyle === "setext" && level < 3) {
          return "\n\n" + text + "\n" + (level === 1 ? "=" : "-").repeat(Math.max(3, text.length)) + "\n\n";
        }
        return "\n\n" + "#".repeat(level) + " " + text + "\n\n";
      },
    });

    // ---- lists: "- item" and "1. item", children indented under the text of their parent
    service.addRule("listItem", {
      filter: "li",
      replacement(content, node, options) {
        const parent = node.parentNode;
        let prefix = options.bulletListMarker + " ";
        if (parent.nodeName === "OL") {
          const start = parseInt(parent.getAttribute("start"), 10);
          const index = Array.prototype.indexOf.call(parent.children, node);
          prefix = (Number.isFinite(start) ? start : 1) + index + ". ";
        }
        const pad = " ".repeat(prefix.length);
        const body = content.replace(/^\n+/, "").replace(/\n+$/, "").replace(/^([\uFDD7\uFDD8])\s*/, "$1 ");
        const text = body.split("\n").map((line, i) => (i && line ? pad + line : line)).join("\n");
        return prefix + text + (node.nextSibling ? "\n" : "");
      },
    });

    // ---- code blocks: always fenced, with the language when the page names it
    service.addRule("codeBlock", {
      filter: "pre",
      replacement(content, node) {
        const code = node.textContent.replace(/\r\n?/g, "\n").replace(/^\n+/, "").replace(/\s+$/, "");
        if (!code) return "";
        let size = 3;
        for (const m of code.matchAll(/^\s*(`{3,})/gm)) size = Math.max(size, m[1].length + 1);
        const fence = "`".repeat(size);
        return "\n\n" + fence + (node.getAttribute("data-excerpt-lang") || "") + "\n" + code + "\n" + fence + "\n\n";
      },
    });

    // ---- links
    const references = [];
    const refNumber = (href) => {
      let i = references.indexOf(href);
      if (i < 0) i = references.push(href) - 1;
      return i + 1;
    };
    service.addRule("link", {
      filter: (node) => node.nodeName === "A" && !!node.getAttribute("href"),
      replacement(content, node) {
        if (node.closest("pre")) return content;
        const href = node.getAttribute("href");
        const label = content.trim();
        if (!label) return "";
        if (node.textContent.trim() === href) return "<" + href + ">";
        const wrap = settings.linkStyle === "reference"
          ? (text) => "[" + text + "][" + refNumber(href) + "]"
          : (text) => "[" + text + "](" + destination(href) + ")";
        // Menu links often sit side by side with only CSS spacing between them: keep them apart.
        const prev = node.previousSibling;
        const glued = prev && prev.nodeName === "A" && (prev.textContent.trim() || prev.querySelector("img"));
        if (!label.includes("\n")) return (glued ? " " : "") + wrap(label);
        // A link around whole blocks (a card): link its heading, or else its first line.
        const lines = label.split("\n");
        let at = lines.findIndex((line) => /^#{1,6} /.test(line));
        if (at < 0) at = lines.findIndex((line) => line.trim());
        const parts = lines[at].match(/^(\s*(?:#{1,6} |> |[-*+] |\d+\. )*)(.*)$/);
        lines[at] = parts[1] + wrap(parts[2]);
        return "\n\n" + lines.join("\n") + "\n\n";
      },
      append() {
        if (!references.length) return "";
        const out = "\n\n" + references.map((href, i) => "[" + (i + 1) + "]: " + href).join("\n") + "\n\n";
        references.length = 0;
        return out;
      },
    });

    // ---- images: always inline, pointing at the picture on the web
    service.addRule("image", {
      filter: "img",
      replacement(content, node) {
        const src = node.getAttribute("src");
        if (!src) return "";
        const alt = (node.getAttribute("alt") || "").replace(/\s+/g, " ").trim().replace(/[\\[\]]/g, "\\$&");
        return "![" + alt + "](" + destination(src) + ")";
      },
    });
    service.addRule("embed", {
      filter: "iframe",
      replacement(content, node) {
        const src = node.getAttribute("src");
        if (!src) return "";
        const title = (node.getAttribute("title") || "").replace(/\s+/g, " ").trim().replace(/[\\[\]]/g, "\\$&");
        return "\n\n[" + (title || "Embedded video") + "](" + destination(src) + ")\n\n";
      },
    });

    // ---- quotes: no trailing space on the empty lines in between
    service.addRule("blockquote", {
      filter: "blockquote",
      replacement(content) {
        const text = content.replace(/^\n+|\n+$/g, "");
        return text ? "\n\n" + text.replace(/^/gm, "> ").replace(/^> $/gm, ">") + "\n\n" : "";
      },
    });
    service.addRule("inlineQuote", {
      filter: "q",
      replacement: (content) => (content.trim() ? '"' + content + '"' : ""),
    });

    // ---- small things Turndown has no rule for
    service.addRule("strikethrough", {
      filter: ["del", "s", "strike"],
      replacement: (content) => (content.trim() ? "~~" + content + "~~" : ""),
    });
    service.addRule("definitionTerm", {
      filter: "dt",
      replacement: (content) => (content.trim() ? "\n\n**" + content.trim() + "**\n\n" : ""),
    });
    service.addRule("details", {
      filter: "details",
      replacement: (content) => "\n\n" + content + "\n\n",
    });
    service.addRule("summary", {
      filter: "summary",
      replacement: (content) => (content.trim() ? "\n\n**" + content.trim() + "**\n\n" : ""),
    });

    // ---- tables
    const kinds = new WeakMap();
    /** A grid of data becomes a Markdown table; a table used for page layout becomes plain blocks. */
    const isData = (table) => {
      if (!table) return false;
      if (kinds.has(table)) return kinds.get(table);
      let data = table.getAttribute("role") !== "presentation" && !table.querySelector("table, pre");
      if (data) {
        const rows = Array.from(table.rows);
        const columns = Math.max(0, ...rows.map((row) => Array.from(row.cells).reduce((n, cell) => n + span(cell, "colspan"), 0)));
        const cells = rows.reduce((n, row) => n + row.cells.length, 0);
        data = cells >= 2 && (columns >= 2 || !!table.querySelector("th"));
      }
      kinds.set(table, data);
      return data;
    };
    service.addRule("tableCell", {
      filter: ["td", "th"],
      replacement(content, node) {
        if (!isData(node.closest("table"))) return "\n\n" + content + "\n\n";
        const text = content.trim().replace(/[ \t]*\n[ \t\n]*/g, "<br>").replace(/\|/g, "\\|");
        return CELL + span(node, "colspan") + "," + span(node, "rowspan") + "," + (node.nodeName === "TH" ? 1 : 0) + SEP + text + CELL_END;
      },
    });
    service.addRule("tableRow", {
      filter: "tr",
      replacement(content, node) {
        if (!isData(node.closest("table"))) return "\n\n" + content + "\n\n";
        return ROW + (node.parentNode.nodeName === "THEAD" ? 1 : 0) + SEP + content + ROW_END;
      },
    });
    service.addRule("tableCaption", {
      filter: "caption",
      replacement(content, node) {
        if (!isData(node.closest("table"))) return "\n\n" + content + "\n\n";
        return CAPTION + content.replace(/\s*\n\s*/g, " ").trim() + CAPTION_END;
      },
    });
    service.addRule("table", {
      filter: "table",
      replacement(content, node) {
        if (!isData(node)) return "\n\n" + content + "\n\n";
        const rows = [];
        for (const r of content.matchAll(ROW_RE)) {
          const cells = [];
          for (const c of r[2].matchAll(CELL_RE)) {
            cells.push({ colspan: Number(c[1]), rowspan: Number(c[2]), heading: c[3] === "1", text: c[4] });
          }
          if (cells.length) rows.push({ inHead: r[1] === "1", cells });
        }
        if (!rows.length) return "";
        // Lay the cells out on a grid. A cell that spans several columns or rows
        // keeps its text in the first slot and leaves the others empty.
        const grid = rows.map(() => []);
        rows.forEach((row, r) => {
          let c = 0;
          for (const cell of row.cells) {
            while (grid[r][c] !== undefined) c++;
            for (let dr = 0; dr < cell.rowspan && r + dr < rows.length; dr++) {
              for (let dc = 0; dc < cell.colspan; dc++) grid[r + dr][c + dc] = dr || dc ? "" : cell.text;
            }
            c += cell.colspan;
          }
        });
        const width = Math.max(...grid.map((cells) => cells.length));
        const line = (cells) => "| " + Array.from({ length: width }, (_, i) => cells[i] || "").join(" | ") + " |";
        const headed = rows[0].inHead || rows[0].cells.every((cell) => cell.heading);
        const out = [line(headed ? grid[0] : []), line(new Array(width).fill("---"))];
        for (let r = headed ? 1 : 0; r < grid.length; r++) out.push(line(grid[r]));
        const caption = (content.match(CAPTION_RE) || [])[1];
        return "\n\n" + (caption ? caption + "\n\n" : "") + out.join("\n") + "\n\n";
      },
    });

    return service;
  }

  /** A tidied, detached element to Markdown text. */
  function toMarkdown(root, settings) {
    tidy(root, settings);
    return makeService(settings).turndown(root)
      .replace(MARKERS, "")
      .replace(/\uFDD7/g, "[x]")
      .replace(/\uFDD8/g, "[ ]")
      .replace(/\u00A0/g, " ") // non-breaking spaces break code when pasted
      .replace(/[\u200B\uFEFF]/g, "")
      .replace(/^[ \t]+$/gm, "")
      .trim();
  }

  // -------------------------------------------------------------- front matter

  const pad2 = (n) => String(n).padStart(2, "0");

  function dateParts(now) {
    const date = now.getFullYear() + "-" + pad2(now.getMonth() + 1) + "-" + pad2(now.getDate());
    const time = pad2(now.getHours()) + ":" + pad2(now.getMinutes());
    return { date, time, datetime: date + "T" + time + ":" + pad2(now.getSeconds()) };
  }

  /** Can this go after "key: " in YAML as it is, without quotes? */
  function plainYaml(value) {
    if (value === "") return true;
    if (/^[\s\-?:,[\]{}#&*!|>'"%@`]/.test(value)) return false;
    if (/: | #|:$/.test(value)) return false;
    return !/^(true|false|null|yes|no|on|off|~)$/i.test(value);
  }

  const doubleQuoted = (value) => value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');

  /**
   * Fill {placeholders} in the user's template. Inside a YAML block (the lines
   * between a first line "---" and the next "---") values are made safe: escaped
   * when the template already put them in quotes, quoted when they stand alone
   * after "key:" and contain something YAML would trip over.
   */
  function renderTemplate(template, values) {
    const lines = String(template).replace(/\r\n?/g, "\n").replace(/\s+$/, "").split("\n");
    const yamlEnd = lines[0].trim() === "---" ? lines.findIndex((line, i) => i > 0 && line.trim() === "---") : -1;
    return lines.map((line, i) => {
      const yaml = i > 0 && i < yamlEnd;
      return line.replace(/\{([a-z]+)\}/g, (whole, key, offset) => {
        if (!Object.prototype.hasOwnProperty.call(values, key)) return whole;
        const value = String(values[key] == null ? "" : values[key]).replace(/\s+/g, " ").trim();
        if (!yaml) return value;
        const before = line.slice(0, offset);
        const after = line.slice(offset + whole.length);
        if ((before.match(/"/g) || []).length % 2 === 1) return doubleQuoted(value);
        if ((before.match(/'/g) || []).length % 2 === 1) return value.replace(/'/g, "''");
        const alone = /^\s*(?:-\s+)?(?:[^:#]+:)?\s*$/.test(before) && after.trim() === "";
        return alone && !plainYaml(value) ? '"' + doubleQuoted(value) + '"' : value;
      }).replace(/[ \t]+$/, ""); // "author: " with no author leaves no trailing space
    }).join("\n");
  }

  // ----------------------------------------------------------------- file name

  /**
   * A file name that every system and every notes app accepts: nothing Windows
   * forbids, and none of # ^ [ ] which break links to the note in Obsidian.
   */
  function fileName(title, fallback) {
    const clean = (s) => Array.from(String(s || "").normalize("NFC")
      .replace(/[\u0000-\u001F\u007F-\u009F<>:"/\\|?*#^[\]]+/g, " ")
      .replace(/\s+/g, " ").replace(/^[. ]+/, ""))
      .slice(0, 100).join("").replace(/[. ]+$/, "");
    let name = clean(title) || clean(fallback) || "clip";
    if (/^(con|prn|aux|nul|com\d|lpt\d)$/i.test(name)) name = "_" + name; // reserved on Windows
    return name + ".md";
  }

  const countWords = (text) => (text.trim().match(/\S+/g) || []).length;

  globalThis.__excerptMarkdown = { toMarkdown, prepare, renderTemplate, dateParts, fileName, countWords };
})();
