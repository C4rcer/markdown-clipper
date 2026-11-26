"""End-to-end test of Excerpt in a real Firefox (Selenium + geckodriver).

  python -m pip install selenium pillow      (once, ideally in a venv)
  python tools/release.py build
  python tests/e2e_firefox.py [main] [ask] [idle]

Loads the built zip as a temporary add-on in throwaway profiles, serves
tests/pages on 127.0.0.1:8961 and compares the Markdown that comes out with the
files in tests/expected, character for character. Every browser runs headless
and muted.

Excerpt only has activeTab, so nothing works until Firefox sees a real user
action. The test makes those through the browser's own UI (geckodriver
--allow-system-access): it clicks the toolbar button, picks the entries in the
right-click menu and presses the keyboard shortcut. Nothing is granted by hand.
The clipboard is Firefox's own headless one; yours is not touched. Saved files
go to a temp folder.

Sessions (all run when none is named):
  main   popup, modes, selections, menu, shortcut, options, front matter, frames,
         strict CSP and sandboxed pages, pages add-ons can not enter
  ask    Firefox set to "always ask where to save files" (the file picker is
         replaced by a stand-in that answers at once)
  idle   the background page asleep before every action, as it usually is
"""
import datetime
import os
import re
import shutil
import sys
import time

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from harness import (ADDON_ID, EXT, ROOT, Fx, Server, big_markdown, unpack_build, wait)

PORT = 8961
BASE = f"http://127.0.0.1:{PORT}"
OTHER_HOST = "excerpt-frame.test"  # mapped to 127.0.0.1: a second site for the cross-origin frame
KOFI = "https://ko-fi.com/carcer7378"
TITLE = "How Tidal Clocks Work"
FILE = TITLE + ".md"
MENU_PAGE = "Clip page as Markdown"
MENU_SELECTION = "Clip selection as Markdown"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    shown = str(detail).replace(chr(10), " / ")[:300]
    line = ("PASS " if ok else "FAIL ") + name + (f"  [{shown}]" if detail != "" else "")
    print(line.encode("ascii", "replace").decode(), flush=True)  # Windows consoles choke on a check mark


def expected(name):
    return (ROOT / "tests" / "expected" / name).read_text(encoding="utf-8").replace("{BASE}", BASE)


def same(name, got, want):
    """Exact comparison; on a mismatch, show the first place where the two differ."""
    if got == want:
        check(name, True)
        return
    if not isinstance(got, str):
        check(name, False, f"got {got!r}")
        return
    at = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
    check(name, False, f"differs at {at}: got {got[max(0, at - 30):at + 40]!r} want {want[max(0, at - 30):at + 40]!r}")


def clear_downloads(fx):
    for p in fx.downloads.iterdir():
        p.unlink()


def grant(fx):
    """Open and close the real popup: the user action that gives the add-on this tab."""
    fx.click_toolbar_button()
    wait(fx.panel_url, 5)
    time.sleep(0.5)
    fx.close_panel()


# Selections on article.html, built the way a mouse drag would leave them, and the Markdown each must give.
SELECTIONS = [
    ("words with bold and italic inside one paragraph", """
        const p = document.getElementById('intro'); const r = document.createRange();
        r.setStart(p.querySelector('strong').firstChild, 0); r.setEnd(p.querySelector('em').firstChild, 4); sel.addRange(r);""",
     "**one pointer**, and that pointer ignores the sun completely: it follows the *moon*\n"),
    ("a heading, a paragraph and the first list item", """
        const r = document.createRange(); r.setStartBefore(document.getElementById('reading'));
        r.setEndAfter(document.querySelector('#post > ul > li')); sel.addRange(r);""",
     "## Reading the dial\n\nThe dial is split in two halves. On the way down the left side the water is falling, "
     "on the way up the right side it is rising:\n\n- Pointer at the top: **high tide**.\n"),
    ("items 2 and 3 of a numbered list keep their numbers", """
        const ol = document.querySelector('#post > ol'); const r = document.createRange();
        r.setStartBefore(ol.children[1]); r.setEndAfter(ol.children[2]); sel.addRange(r);""",
     "2. Wait for that moment, ideally near a full or new moon.\n   1. Put in a fresh battery.\n"
     "   2. Turn the pointer to \"High Tide\".\n3. Check it again after a month.\n"),
    ("part of a code block stays a code block, with its language", """
        const t = document.querySelector('code.language-js').firstChild; const r = document.createRange();
        r.setStart(t, t.data.indexOf('function')); r.setEnd(t, t.data.length); sel.addRange(r);""",
     "```js\nfunction pointerAngle(now, lastHighTide) {\n  const phase = ((now - lastHighTide) % TIDE_MS) / TIDE_MS;\n"
     "  return phase * 360; // 0 = high tide, 180 = low tide\n}\n```\n"),
    ("code whose language is named on a wrapper around it", """
        const t = document.querySelector('.highlight-source-python pre').firstChild; const r = document.createRange();
        r.setStart(t, 0); r.setEnd(t, t.data.indexOf('def') - 2); sel.addRange(r);""",
     "```python\nTIDE_S = 44714\n```\n"),
    ("a few characters of inline code stay code", """
        const t = document.querySelector('#post p code').firstChild; const r = document.createRange();
        r.setStart(t, 0); r.setEnd(t, 3); sel.addRange(r);""",
     "`447`\n"),
    ("two table rows become a table", """
        const b = document.querySelector('#drift-table tbody'); const r = document.createRange();
        r.setStartBefore(b.rows[1]); r.setEndAfter(b.rows[2]); sel.addRange(r);""",
     "|  |  |  |\n| --- | --- | --- |\n| First quarter | Neap | up to 60 min |\n| Last quarter | Neap | up to 60 min |\n"),
    ("table cells picked one by one (how Firefox selects when dragging across cells)", """
        const b = document.querySelector('#drift-table tbody');
        for (const [row, cell] of [[0, 0], [0, 1], [1, 0], [1, 1]]) {
          const r = document.createRange(); r.selectNode(b.rows[row].cells[cell]); sel.addRange(r);
        }""",
     "|  |  |\n| --- | --- |\n| New or full | Spring |\n| First quarter | Neap |\n"),
    ("the whole table, heading row included", """
        const r = document.createRange(); r.selectNode(document.getElementById('drift-table')); sel.addRange(r);""",
     "| Moon phase | Tide type | Typical error |\n| --- | --- | --- |\n| New or full | Spring | under 10 min |\n"
     "| First quarter | Neap | up to 60 min |\n| Last quarter | Neap | up to 60 min |\n"),
    ("words out of a quote stay plain words", """
        const t = document.querySelector('#quote p').firstChild; const r = document.createRange();
        r.setStart(t, t.data.indexOf('forgive')); r.setEnd(t, t.data.indexOf('forgive') + 10); sel.addRange(r);""",
     "forgive it\n"),
    ("a picture inside a link, with the words around it", """
        const p = document.querySelector('#post a[href$=".pdf"]').parentNode; const r = document.createRange();
        r.setStart(p.childNodes[2], p.childNodes[2].data.indexOf('use a table')); r.setEndAfter(p.querySelector('a')); sel.addRange(r);""",
     f"use a table. A [![Tide table for 2026]({BASE}/img/table-thumb.png)]({BASE}/downloads/tide-table-2026.pdf)\n"),
]

TRICKY_TEMPLATE = """---
title: {title}
quoted: "{title}"
single: '{title}'
source: {url}
author: {author}
site: {site}
published: {published}
description: {description}
tags: [clip, {site}]
unknown: {nope}
---
Clipped {date} at {time} ({datetime}) from {title}"""

TRICKY_HEAD = f"""---
title: "Tom's \\"Tide\\": notes #1"
quoted: "Tom's \\"Tide\\": notes #1"
single: 'Tom''s "Tide": notes #1'
source: {BASE}/tricky.html
author: A. B. O'Neil
site: 127.0.0.1
published:
description: "Notes: a \\"quoted\\" summary"
tags: [clip, 127.0.0.1]
unknown: {{nope}}
---
"""


def today():
    return datetime.datetime.now().strftime("%Y-%m-%d")


def session_main(unpacked, srv):
    fx = Fx(unpacked, hosts=[OTHER_HOST])
    d = fx.d
    article = expected("article.md")
    try:
        # ------------------------------------------------ the toolbar button, clicked for real
        fx.open(srv.url("article.html"))
        check("no access to the page before the user acts", fx.has_active_tab() is False)
        where = fx.click_toolbar_button()
        check("toolbar button sits in the navigation bar", where == "nav-bar", where)
        url = wait(fx.panel_url, 5)
        check("clicking it opens the popup", isinstance(url, str) and url.endswith("/popup/popup.html"), url)
        check("and gives activeTab for this tab", fx.has_active_tab() is True)
        wait(lambda: fx.panel_eval("content.document.getElementById('copy').disabled") is False, 6)
        same("real popup: preview is the article as Markdown",
             fx.panel_eval("content.document.getElementById('preview').value"), article)
        check("real popup: Copy has the focus, so Enter copies",
              fx.panel_eval("content.document.activeElement && content.document.activeElement.id") == "copy")
        fx.clear_clipboard()
        fx.focus_panel()
        fx.press(Keys.ENTER)
        same("real popup: Enter copies the Markdown", fx.copied(), article)
        check("real popup: says Copied", wait(lambda: "Copied" in (fx.panel_eval("content.document.getElementById('copy').textContent") or ""), 3))
        fx.chrome("""
          const b = document.querySelector("browser.webextension-popup-browser");
          b.messageManager.loadFrameScript("data:," + encodeURIComponent("content.document.getElementById('save').click();"), false);
        """)
        same("real popup: Save writes a .md file named after the article", fx.saved(FILE), article)
        check("real popup: no other file appeared", fx.saved_names() == [FILE], fx.saved_names())
        fx.close_panel()
        clear_downloads(fx)

        perms = fx.api("return (await browser.permissions.getAll());")
        check("no host permissions at all", perms.get("origins") == [], perms)
        check("permissions are activeTab, menus, scripting, storage",
              sorted(perms.get("permissions", [])) == ["activeTab", "menus", "scripting", "storage"], perms.get("permissions"))
        check("two clips counted so far (copy and save)", wait(lambda: fx.clips() == 2, 3), fx.clips())

        # ------------------------------------------------ popup (as a tab in the second window, pointed at the page)
        before_html = fx.js("return document.documentElement.outerHTML")
        before_requests = len(srv.requests)
        fx.popup()
        same("popup: article mode by default", fx.preview(), article)
        check("popup: Article is the checked mode",
              d.find_element(By.CSS_SELECTOR, '#mode button[data-mode="article"]').get_attribute("aria-checked") == "true")
        check("popup: Selection is switched off while nothing is selected",
              not d.find_element(By.CSS_SELECTOR, '#mode button[data-mode="selection"]').is_enabled())
        check("popup: shows word and character counts", d.find_element(By.ID, "count").text == f"520 words \u00b7 {len(article):,} characters",
              d.find_element(By.ID, "count").text.encode("ascii", "replace").decode())
        check("popup: shows the file name", d.find_element(By.ID, "file").text == FILE, d.find_element(By.ID, "file").text)
        check("popup: shows the shortcut", wait(lambda: d.find_element(By.ID, "shortcut").text == "Alt+Shift+M", 3),
              d.find_element(By.ID, "shortcut").text)
        check("popup: has the Ko-fi pill",
              d.find_element(By.CSS_SELECTOR, "header a[data-support]").get_attribute("href") == KOFI)
        check("popup: no thank-you card for a new user", not d.find_element(By.ID, "supportCard").is_displayed())
        check("popup: no note about a missing article", not d.find_element(By.ID, "note").is_displayed())

        fx.clear_clipboard()
        fx.to_ext()
        d.find_element(By.ID, "copy").click()
        same("popup: Copy puts the Markdown on the clipboard", fx.copied(), article)
        fx.to_ext()
        check("popup: button and toast confirm the copy",
              "Copied" in d.find_element(By.ID, "copy").text and "Copied as Markdown" in d.find_element(By.ID, "toast").text)
        d.find_element(By.ID, "save").click()
        same("popup: Save writes the file", fx.saved(FILE), article)
        fx.to_ext()
        check("popup: toast names the saved file", FILE in d.find_element(By.ID, "toast").text, d.find_element(By.ID, "toast").text)
        clear_downloads(fx)

        same("popup: Whole page mode has the menus, sidebar and footer too", fx.popup_mode("page"), expected("article-page.md"))
        same("popup: back to Article", fx.popup_mode("article"), article)

        d.find_element(By.ID, "preview").send_keys(Keys.CONTROL, Keys.END)
        d.find_element(By.ID, "preview").send_keys("My own note.")
        check("popup: the preview can be edited, the count follows",
              d.find_element(By.ID, "count").text.startswith("523 words"), d.find_element(By.ID, "count").text[:12])
        fx.clear_clipboard()
        fx.to_ext()
        d.find_element(By.ID, "copy").click()
        same("popup: Copy takes the edited text", fx.copied(), article + "My own note.")
        fx.to_ext()
        d.find_element(By.ID, "save").click()
        same("popup: Save takes the edited text", fx.saved(FILE), article + "My own note.")
        clear_downloads(fx)

        check("clipping left the page exactly as it was", fx.js("return document.documentElement.outerHTML") == before_html)
        check("clipping loaded nothing from the site (not even the lazy image)",
              len(srv.requests) == before_requests and not any("lazy-moonrise" in r for r in srv.requests),
              srv.requests[before_requests:])

        # ------------------------------------------------ selections
        for name, script, want in SELECTIONS:
            fx.select(script)
            fx.popup()
            same("selection: " + name, fx.preview(), want)
        fx.to_ext()
        sel_btn = d.find_element(By.CSS_SELECTOR, '#mode button[data-mode="selection"]')
        check("popup: with text selected it opens in Selection mode",
              sel_btn.is_enabled() and sel_btn.get_attribute("aria-checked") == "true")
        same("popup: Article is still one click away", fx.popup_mode("article"), article)
        same("popup: and back to Selection", fx.popup_mode("selection"), SELECTIONS[-1][2])
        fx.select("")
        fx.popup()
        same("popup: selection gone, article again", fx.preview(), article)

        # ------------------------------------------------ right-click menu, for real
        fx.clear_clipboard()
        labels = fx.menu_labels("#intro")
        check("menu: on the page there is one entry, Clip page", labels == [MENU_PAGE], labels)
        clips = fx.clips()
        check("menu: Clip page can be chosen", fx.menu_click("#intro", MENU_PAGE) is True)
        same("menu: Clip page copies the article", fx.copied(), article)
        check("menu: the page confirms it", wait(lambda: fx.toast() == "\u2713 Copied 520 words as Markdown", 4),
              (fx.toast() or "").encode("ascii", "replace").decode())
        check("menu: the clip is counted", wait(lambda: fx.clips() == clips + 1, 3))
        check("menu: the confirmation goes away by itself", wait(lambda: fx.toast() is None, 5))
        check("menu: and the page is as it was", fx.js("return document.documentElement.outerHTML") == before_html)

        fx.select(SELECTIONS[0][1])
        labels = fx.menu_labels("#intro strong")
        check("menu: on selected text there is one entry, Clip selection", labels == [MENU_SELECTION], labels)
        fx.clear_clipboard()
        fx.menu_click("#intro strong", MENU_SELECTION)
        same("menu: Clip selection copies the selection", fx.copied(), SELECTIONS[0][2])
        check("menu: with the word count", wait(lambda: fx.toast() == "\u2713 Copied 13 words as Markdown", 4),
              (fx.toast() or "").encode("ascii", "replace").decode())

        # ------------------------------------------------ keyboard shortcut, pressed for real
        fx.clear_clipboard()
        fx.shortcut()
        same("shortcut: with text selected it clips the selection", fx.copied(), SELECTIONS[0][2])
        fx.select("")
        fx.clear_clipboard()
        fx.shortcut()
        same("shortcut: without a selection it clips the article", fx.copied(), article)

        # ------------------------------------------------ menu and shortcut set to save a file
        fx.settings(quickAction="save")
        wait(lambda: fx.toast() is None, 5)
        fx.clear_clipboard()
        fx.menu_click("#intro", MENU_PAGE)
        same("save: Clip page writes the file", fx.saved(FILE), article)
        check("save: the page names the file", wait(lambda: fx.toast() == "\u2713 Saved " + FILE, 4),
              (fx.toast() or "").encode("ascii", "replace").decode())
        check("save: the clipboard is left alone", fx.clipboard() is None, fx.clipboard())
        clear_downloads(fx)
        fx.select(SELECTIONS[3][1])
        fx.shortcut()
        same("save: the shortcut saves the selection", fx.saved(FILE), SELECTIONS[3][2])
        clear_downloads(fx)
        fx.select("")
        fx.settings(quickAction="copy")

        # ------------------------------------------------ the edge-case page
        fx.open(srv.url("extras.html"))
        grant(fx)
        fx.popup()
        same("edge cases: article mode", fx.preview(), expected("extras-article.md"))
        same("edge cases: whole page mode leaves out what is hidden", fx.popup_mode("page"), expected("extras-page.md"))
        fx.js("const a = document.getElementById('area'); a.focus(); a.setSelectionRange(0, 4);")
        labels = fx.menu_labels("#area")
        check("menu: text selected in a text box offers Clip selection", labels == [MENU_SELECTION], labels)
        fx.clear_clipboard()
        fx.menu_click("#area", MENU_SELECTION)
        same("menu: text from a text box is copied as it is", fx.copied(), "area\n")

        # ------------------------------------------------ web components (shadow trees)
        fx.open(srv.url("shadow.html"))
        grant(fx)
        fx.popup()
        same("components: article mode includes what their shadow trees show", fx.preview(), expected("shadow.md"))
        same("components: whole page mode too", fx.popup_mode("page"), expected("shadow.md"))
        fx.select("""
          const lead = document.getElementById('lead').firstChild; const em = document.querySelector('#note em').firstChild;
          sel.setBaseAndExtent(lead, lead.data.indexOf('a clip has'), em, 3);""")
        fx.popup()
        same("components: a selection that runs across two of them", fx.preview(),
             "a clip has to contain what a reader sees in each.\n\n```js\nconst high = 12.42;\nconst low = high / 2;\n```\n\n"
             "A note whose label comes from the component and whose text comes from the page:\n\n**Note:** Slotted *lig*\n")
        fx.select("")
        spot = fx.js("const r = document.getElementById('code').shadowRoot.querySelector('code').getBoundingClientRect(); return [r.left + 30, r.top + 8];")
        fx.to_page()
        ac = ActionChains(d)
        ac.w3c_actions.pointer_action.move_to_location(int(spot[0]), int(spot[1]))
        ac.double_click().perform()
        check("components: a double-click selects a word inside a shadow tree", fx.js("return getSelection().toString().trim()") == "const",
              fx.js("return getSelection().toString()"))
        fx.popup()
        same("components: that selection is clipped as code, with the language of the component", fx.preview(), "```js\nconst\n```\n")
        fx.select("")

        # ------------------------------------------------ options page
        fx.to_ext()
        d.get(f"{EXT}/options/options.html")
        wait(lambda: d.find_element(By.ID, "shortcut").text == "Alt+Shift+M", 4)
        check("options: shows the shortcut", d.find_element(By.ID, "shortcut").text == "Alt+Shift+M")
        check("options: has the Ko-fi link", d.find_element(By.CSS_SELECTOR, "a[data-support]").get_attribute("href") == KOFI)
        check_more_addons(fx.api)
        check_milestone_card(fx.api)
        checked = {n: d.find_element(By.CSS_SELECTOR, f'input[name="{n}"]:checked').get_attribute("value")
                   for n in ("headingStyle", "bullet", "linkStyle", "quickAction")}
        check("options: start at the defaults",
              checked == {"headingStyle": "atx", "bullet": "-", "linkStyle": "inline", "quickAction": "copy"}
              and d.find_element(By.ID, "images").is_selected() and d.find_element(By.ID, "titleHeading").is_selected()
              and not d.find_element(By.ID, "frontMatter").is_selected(), checked)
        check("options: lists the nine placeholders",
              [e.text for e in d.find_elements(By.CSS_SELECTOR, "#placeholders dt")]
              == ["{title}", "{url}", "{date}", "{time}", "{datetime}", "{author}", "{site}", "{description}", "{published}"])
        for css in ('input[name="headingStyle"][value="setext"]', 'input[name="bullet"][value="*"]',
                    'input[name="linkStyle"][value="reference"]', "#images", "#titleHeading"):
            d.find_element(By.CSS_SELECTOR, css).click()
        got = wait(lambda: (lambda s: s if s.get("titleHeading") is False else None)(fx.store().get("settings") or {}), 4)
        check("options: every change is saved at once",
              isinstance(got, dict) and got.get("headingStyle") == "setext" and got.get("bullet") == "*"
              and got.get("linkStyle") == "reference" and got.get("images") is False, got)

        fx.open(srv.url("article.html"))
        grant(fx)
        fx.popup()
        same("options: underlined headings, * bullets, numbered links, no images, no title", fx.preview(), expected("article-options.md"))
        fx.settings(headingStyle="atx", bullet="+", linkStyle="inline", images=True, titleHeading=True)
        fx.popup()
        same("options: + bullets", fx.preview(), article.replace("\n- ", "\n+ ").replace("\n  - ", "\n  + "))
        fx.settings(bullet="-")

        # ------------------------------------------------ front matter
        fx.to_ext()
        d.get(f"{EXT}/options/options.html")
        wait(lambda: d.find_element(By.ID, "template").get_attribute("value") != "", 4)
        default_template = d.find_element(By.ID, "template").get_attribute("value")
        check("front matter: the default template has title, source and date",
              default_template == '---\ntitle: "{title}"\nsource: {url}\nclipped: {date}\n---', default_template)
        check("front matter: Reset is off while the template is the default", not d.find_element(By.ID, "templateReset").is_enabled())
        d.find_element(By.ID, "frontMatter").click()
        wait(lambda: (fx.store().get("settings") or {}).get("frontMatter") is True, 4)
        day = today()
        fx.popup()
        head = f'---\ntitle: "{TITLE}"\nsource: {BASE}/article.html\nclipped: {{}}\n---\n\n'
        got = fx.preview()
        check("front matter: default block on top of the article", got in (head.format(day) + article, head.format(today()) + article),
              got[:120])
        check("front matter: the popup box is ticked", d.find_element(By.ID, "frontMatter").is_selected())
        fx.select(next(s for s in SELECTIONS if s[0].startswith("words out of a quote"))[1])
        fx.popup()
        got = fx.preview()
        check("front matter: on a selection too", got in (head.format(day) + "forgive it\n", head.format(today()) + "forgive it\n"), got[:120])
        fx.select("")
        fx.clear_clipboard()
        fx.shortcut()
        got = fx.copied()
        check("front matter: the shortcut includes it", got in (head.format(day) + article, head.format(today()) + article), (got or "")[:80])
        fx.popup()
        d.find_element(By.ID, "frontMatter").click()
        check("front matter: unticking it in the popup takes it off again", wait(lambda: fx.preview() == article, 5))
        check("front matter: and that is saved", (fx.store().get("settings") or {}).get("frontMatter") is False)

        fx.to_ext()
        d.get(f"{EXT}/options/options.html")
        wait(lambda: d.find_element(By.ID, "template").get_attribute("value") != "", 4)
        box = d.find_element(By.ID, "template")
        box.send_keys(Keys.CONTROL, "a")
        box.send_keys("Source: {url}")
        check("front matter: a typed template is saved",
              wait(lambda: (fx.store().get("settings") or {}).get("frontMatterTemplate") == "Source: {url}", 4)
              and wait(lambda: d.find_element(By.ID, "templateState").text == "Saved", 3))
        fx.settings(frontMatter=True)
        fx.popup()
        same("front matter: a template that is not YAML is used as it is", fx.preview(), f"Source: {BASE}/article.html\n\n" + article)
        fx.to_ext()
        d.get(f"{EXT}/options/options.html")
        wait(lambda: d.find_element(By.ID, "templateReset").is_enabled(), 4)
        d.find_element(By.ID, "templateReset").click()
        check("front matter: Reset brings the default back",
              wait(lambda: (fx.store().get("settings") or {}).get("frontMatterTemplate") == default_template, 4)
              and d.find_element(By.ID, "template").get_attribute("value") == default_template)

        fx.settings(frontMatterTemplate=TRICKY_TEMPLATE)
        fx.open(srv.url("tricky.html"))
        grant(fx)
        fx.popup()
        got = fx.preview()
        tail = got[len(TRICKY_HEAD):] if got.startswith(TRICKY_HEAD) else ""
        same("front matter: quotes, colons and # in a title are made safe for YAML", got[:len(TRICKY_HEAD)], TRICKY_HEAD)
        m = re.match(r"Clipped (\d{4}-\d\d-\d\d) at (\d\d:\d\d) \((\d{4}-\d\d-\d\d)T(\d\d:\d\d):\d\d\) from Tom's \"Tide\": notes #1\n\n", tail)
        check("front matter: date, time and datetime outside the YAML block",
              bool(m) and m.group(1) == m.group(3) and m.group(2) == m.group(4) and m.group(1) in (day, today()), tail[:90])
        check("front matter: then the article, starting with its title",
              bool(m) and tail[m.end():].startswith("# Tom's \"Tide\": notes #1\n\nThese are working notes"), tail[:140])
        check("file name: no quotes, colon or # in it", d.find_element(By.ID, "file").text == "Tom's Tide notes 1.md",
              d.find_element(By.ID, "file").text)
        fx.to_ext()
        d.find_element(By.ID, "save").click()
        check("file name: Firefox saves it under exactly that name", fx.saved("Tom's Tide notes 1.md") == got, fx.saved_names())
        clear_downloads(fx)
        fx.settings(frontMatter=False, frontMatterTemplate=default_template)

        # ------------------------------------------------ frames
        fx.open(srv.url("frames.html"))
        fx.js(f"document.getElementById('cross').src = 'http://{OTHER_HOST}:{PORT}/frame-inner.html';")
        time.sleep(1.0)
        for frame in ("#same", "#cross"):
            fx.to_page()
            d.switch_to.frame(d.find_element(By.CSS_SELECTOR, frame))
            d.execute_script("const s = getSelection(); s.removeAllRanges(); s.selectAllChildren(document.getElementById('inner'));")
            d.switch_to.default_content()
            fx.clear_clipboard()
            ok = fx.menu_click("#inner", MENU_SELECTION, frame=frame)
            got = fx.copied()
            if frame == "#same":
                same("frames: a selection inside a frame of the same site keeps its formatting", got, "Frame text with **bold** words.\n")
            else:
                same("frames: a selection inside a frame from another site comes as plain text", got, "Frame text with bold words.\n")
            check(f"frames: menu entry was there in {frame}", ok is True)
            fx.to_page()
            d.switch_to.frame(d.find_element(By.CSS_SELECTOR, frame))
            d.execute_script("getSelection().removeAllRanges();")
            d.switch_to.default_content()
            time.sleep(0.3)

        # ------------------------------------------------ pages without an article
        fx.open(srv.url("links.html"))
        grant(fx)
        fx.popup()
        same("a page of links: clipped as it is", fx.preview(), f"# Start\n\n[Alpha]({BASE}/a) [Beta]({BASE}/b)\n")
        fx.open(srv.url("gallery.html"))
        grant(fx)
        fx.popup()
        same("no article (only pictures): falls back to the whole page", fx.preview(),
             f"# Harbor photos\n\n![The quay at low tide]({BASE}/img/quay.jpg) ![The lighthouse]({BASE}/img/lighthouse.jpg)\n")
        check("no article: the popup says so, and shows Whole page as the mode",
              d.find_element(By.ID, "note").is_displayed() and "whole page" in d.find_element(By.ID, "note").text
              and d.find_element(By.CSS_SELECTOR, '#mode button[data-mode="page"]').get_attribute("aria-checked") == "true")
        fx.open(srv.url("empty.html"))
        grant(fx)
        fx.popup()
        check("empty page: the popup says there is nothing to clip",
              d.find_element(By.ID, "error").is_displayed() and "nothing to clip" in d.find_element(By.ID, "error").text
              and not d.find_element(By.ID, "copy").is_enabled(), d.find_element(By.ID, "error").text)
        fx.open(srv.url("drawing.svg"))
        grant(fx)
        fx.popup()
        check("an SVG file: the popup says it only works on web pages",
              d.find_element(By.ID, "error").is_displayed() and "kind of document" in d.find_element(By.ID, "error").text,
              d.find_element(By.ID, "error").text)

        # ------------------------------------------------ a very long article, clipped with the shortcut
        n = 6000
        fx.open(srv.url(f"big.html?n={n}"))
        fx.clear_clipboard()
        started = time.time()
        fx.shortcut()
        got = fx.copied(60)
        took = time.time() - started
        same(f"long article: {n} paragraphs arrive complete on the clipboard", got, big_markdown(n, BASE))
        check("long article: in reasonable time", took < 30, f"{took:.1f} s")

        # ------------------------------------------------ strict Content-Security-Policy page
        fx.open(srv.url("article.html?csp=strict"))
        blocked = fx.js("""
          const s = document.createElement('style'); s.textContent = '#intro { outline: 5px solid red }'; document.head.append(s);
          return getComputedStyle(document.getElementById('intro')).outlineStyle;""")
        check("CSP page really blocks injected styles", blocked == "none", blocked)
        fx.clear_clipboard()
        fx.shortcut()
        same("strict CSP: the shortcut still clips", fx.copied(), article)
        style = wait(lambda: fx.js("""
          const t = document.querySelector('[data-excerpt-toast]'); if (!t) return null;
          const s = getComputedStyle(t); return [s.position, s.backgroundColor, t.matches(':popover-open')];"""), 4)
        check("strict CSP: the confirmation is styled and on top", style == ["fixed", "rgb(22, 22, 26)", True], style)

        # ------------------------------------------------ a page served with "Content-Security-Policy: sandbox"
        fx.open(srv.url("article.html?csp=sandbox"))
        check("sandboxed page has an opaque origin", fx.js("return window.origin") == "null")
        fx.clear_clipboard()
        fx.shortcut()
        same("sandboxed page: copy works", fx.copied(), article)
        fx.settings(quickAction="save")
        fx.shortcut()
        same("sandboxed page: saving works too (the add-on saves, the page may not)", fx.saved(FILE), article)
        clear_downloads(fx)
        fx.settings(quickAction="copy")

        # ------------------------------------------------ the one-time thank-you card
        fx.open(srv.url("article.html"))
        grant(fx)
        fx.api("await browser.storage.local.set({ stats: { clips: 24 } }); return true;")
        fx.popup()
        check("thank-you card: not before 25 clips", not d.find_element(By.ID, "supportCard").is_displayed())
        d.find_element(By.ID, "copy").click()
        wait(lambda: fx.clips() == 25, 3)
        fx.popup()
        card = d.find_element(By.ID, "supportCard")
        check("thank-you card: appears once 25 pages are clipped, inside the popup only",
              card.is_displayed() and "clipped 25 pages" in card.text, card.text[:60])
        check("thank-you card: the first one asks for a rating, with a link to Excerpt's AMO page",
              card.find_element(By.CSS_SELECTOR, "a[data-rate-ask]").get_attribute("href")
              == "https://addons.mozilla.org/firefox/addon/excerpt-markdown-web-clipper/" and "rating on Firefox Add-ons" in card.text, card.text)
        [b for b in card.find_elements(By.CSS_SELECTOR, "button") if b.text == "Don't ask again"][0].click()
        check("thank-you card: Don't ask again is remembered", wait(lambda: (fx.store().get("supportNudge") or {}).get("optOut") is True, 3))
        fx.popup()
        time.sleep(0.4)
        check("thank-you card: and it stays away", not d.find_element(By.ID, "supportCard").is_displayed())

        # ------------------------------------------------ a page Firefox keeps add-ons out of
        fx.open("about:addons")
        fx.popup()
        check("blocked page: the popup explains",
              d.find_element(By.ID, "error").is_displayed() and "doesn't let add-ons" in d.find_element(By.ID, "error").text,
              d.find_element(By.ID, "error").text)
        fx.clear_clipboard()
        fx.shortcut()
        check("blocked page: the shortcut flags the toolbar button", wait(lambda: fx.badge() == "!", 3))
        check("blocked page: nothing is copied", fx.clipboard() is None)
        check("blocked page: the flag clears itself", wait(lambda: fx.badge() == "", 5))
    finally:
        fx.quit()


def session_ask(unpacked, srv):
    """Firefox set to ask where to save every file. A stand-in file picker answers at once and notes who asked."""
    fx = Fx(unpacked, prefs={"browser.download.useDownloadDir": False})
    article = expected("article.md")
    try:
        fx.open(srv.url("article.html"))
        fx.chrome("""
          const dir = arguments[0];
          const calls = [];
          const picker = {
            QueryInterface: ChromeUtils.generateQI(["nsIFilePicker"]),
            defaultString: "", defaultExtension: "", filterIndex: 0, displayDirectory: null,
            displaySpecialDirectory: "", addToRecentDocs: false, okButtonLabel: "", mode: 0,
            init(bc, title, mode) {
              let parent = null;
              try { parent = bc.currentWindowGlobal.documentURI.spec; } catch (e) { parent = null; }
              calls.push({ parent, mode });
            },
            appendFilters() {}, appendFilter() {}, appendRawFilter() {},
            get file() {
              const f = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
              f.initWithPath(PathUtils.join(dir, this.defaultString));
              return f;
            },
            get fileURL() { return Services.io.newFileURI(this.file); },
            get domFileOrDirectory() { return null; },
            open(callback) {
              calls[calls.length - 1].name = this.defaultString;
              Services.tm.dispatchToMainThread(() => callback.done(Ci.nsIFilePicker.returnOK));
            },
          };
          const factory = { createInstance(iid) { return picker.QueryInterface(iid); } };
          Components.manager.QueryInterface(Ci.nsIComponentRegistrar)
            .registerFactory(Services.uuid.generateUUID(), "", "@mozilla.org/filepicker;1", factory);
          window.__excerptPicker = { picker, factory, calls };
        """, str(fx.downloads))

        def asked():
            return fx.chrome("return JSON.parse(JSON.stringify(window.__excerptPicker.calls))")

        fx.click_toolbar_button()
        wait(fx.panel_url, 5)
        wait(lambda: fx.panel_eval("content.document.getElementById('copy').disabled") is False, 6)
        fx.chrome("""
          const b = document.querySelector("browser.webextension-popup-browser");
          b.messageManager.loadFrameScript("data:," + encodeURIComponent("content.document.getElementById('save').click();"), false);
        """)
        same("ask: Save in the popup goes through Firefox's Save dialog and lands", fx.saved(FILE), article)
        calls = asked()
        check("ask: the dialog was offered the article's name, from the browser window",
              len(calls) == 1 and calls[0].get("name") == FILE and calls[0].get("parent") == "chrome://browser/content/browser.xhtml", calls)
        fx.close_panel()
        clear_downloads(fx)

        fx.settings(quickAction="save")
        fx.shortcut()
        same("ask: the shortcut's save asks too, and lands", fx.saved(FILE), article)
        calls = asked()
        check("ask: again from the browser window (the save is started by the page)",
              len(calls) == 2 and calls[1].get("name") == FILE and calls[1].get("parent") == "chrome://browser/content/browser.xhtml", calls)
        clear_downloads(fx)

        fx.open(srv.url("article.html?csp=sandbox"))
        fx.shortcut()
        same("ask: a sandboxed page is saved by the add-on itself", fx.saved(FILE), article)
        calls = asked()
        check("ask: and the dialog still gets the right name", len(calls) == 3 and calls[2].get("name") == FILE, calls)
    finally:
        fx.quit()


def session_idle(unpacked, srv):
    """Firefox stops an idle background page after 30 seconds (here: 1.5). Most right-clicks and
    shortcut presses in real use arrive while it is asleep and have to wake it."""
    fx = Fx(unpacked, prefs={"extensions.background.idle.timeout": 1500})
    article = expected("article.md")

    def asleep():
        return wait(lambda: fx.chrome(
            "return WebExtensionPolicy.getByID(arguments[0]).extension.backgroundState;", ADDON_ID) == "stopped", 20) is True
    try:
        fx.open(srv.url("article.html"))
        check("idle: the background page goes to sleep", asleep())
        labels = fx.menu_labels("#intro")
        check("idle: the menu entry is still there", labels == [MENU_PAGE], labels)
        check("idle: asleep before the shortcut", asleep())
        fx.clear_clipboard()
        fx.shortcut()
        same("idle: the shortcut wakes it and the article is copied", fx.copied(), article)
        check("idle: asleep again before the menu", asleep())
        fx.clear_clipboard()
        fx.menu_click("#intro", MENU_PAGE)
        same("idle: the menu wakes it and the article is copied", fx.copied(), article)
        fx.settings(quickAction="save")
        fx.select(SELECTIONS[0][1])
        check("idle: asleep again before saving", asleep())
        fx.menu_click("#intro strong", MENU_SELECTION)
        same("idle: saving a selection from the menu works after a wake-up too", fx.saved(FILE), SELECTIONS[0][2])
        check("idle: asleep before the popup", asleep())
        fx.click_toolbar_button()
        wait(fx.panel_url, 5)
        wait(lambda: fx.panel_eval("content.document.getElementById('copy').disabled") is False, 8)
        same("idle: the popup wakes it for its preview", fx.panel_eval("content.document.getElementById('preview').value"), SELECTIONS[0][2])
        fx.close_panel()
    finally:
        fx.quit()


SESSIONS = {"main": session_main, "ask": session_ask, "idle": session_idle}


def check_more_addons(api):
    """Rate pill and "More free add-ons" card on the settings page that is open now.
    The expected list comes from the shared file, so a new round only flips `live` flags."""
    more = wait(lambda: api("""
      const items = [...document.querySelectorAll('#moreAddons .more-item a')];
      if (!items.length) return null;
      const rate = document.querySelector('[data-rate]');
      const all = document.querySelector('[data-more-all]');
      const m = await import('/shared/more-addons.js');
      const me = browser.runtime.id;
      const self = m.ADDONS.find((a) => a.id === me);
      const fake = [{id: 'a', live: true, android: false}, {id: 'b', live: true, android: true},
                    {id: 'self', live: true, android: true}, {id: 'c', live: false, android: true}];
      return {
        names: items.map((a) => a.querySelector('.more-name').textContent),
        expected: m.ADDONS.filter((a) => a.live && a.id !== me).map((a) => a.name),
        left_out: m.ADDONS.filter((a) => !a.live || a.id === me).map((a) => a.name),
        self_slug: self ? self.slug : null, self_live: self ? self.live : null,
        hrefs: items.map((a) => a.href),
        newTab: items.every((a) => a.target === '_blank' && a.rel === 'noopener'),
        rate: rate.hidden ? null : rate.href, rateNewTab: rate.target === '_blank',
        all: all.href,
        androidPick: m.moreAddons('self', 'android', fake).map((x) => x.id),
        desktopPick: m.moreAddons('self', 'win', fake).map((x) => x.id),
      };
    """))
    more = more if isinstance(more, dict) else {}
    check("this add-on is marked live in the shared add-on list", more.get("self_live") is True, more.get("self_slug"))
    check("settings page lists every other live add-on, in order",
          bool(more.get("names")) and more.get("names") == more.get("expected"), (more.get("names"), more.get("expected")))
    check("it leaves out itself and add-ons still in review",
          bool(more.get("names")) and not set(more["names"]) & set(more.get("left_out") or []), more.get("left_out"))
    check("each listed add-on links to its AMO page in a new tab",
          bool(more.get("hrefs")) and all(h.startswith("https://addons.mozilla.org/firefox/addon/") for h in more["hrefs"])
          and more.get("newTab") is True, more.get("hrefs"))
    check("rate link opens this add-on's own AMO page",
          bool(more.get("self_slug")) and more.get("rate") == "https://addons.mozilla.org/firefox/addon/%s/" % more.get("self_slug")
          and more.get("rateNewTab") is True, more.get("rate"))
    check("see-all link opens the author's AMO page",
          more.get("all") == "https://addons.mozilla.org/firefox/user/20013808/", more.get("all"))
    check("list skips itself and unreleased add-ons, and desktop-only ones on Android",
          more.get("desktopPick") == ["a", "b"] and more.get("androidPick") == ["b"],
          (more.get("desktopPick"), more.get("androidPick")))


def check_milestone_card(api):
    """The shared thank-you card, driven directly on the extension page that is open now:
    the first card a user ever gets asks for a rating, later ones for a tip. Leaves storage as it found it."""
    out = api("""
      const m = await import('/shared/support.js');
      const lists = await import('/shared/more-addons.js');
      const self = lists.ADDONS.find((a) => a.id === browser.runtime.id);
      const KEY = 'supportNudge';
      const saved = (await browser.storage.local.get(KEY))[KEY];
      const box = document.createElement('div');
      document.body.append(box);
      box.addEventListener('click', (e) => e.preventDefault(), true);  // a test click must not open AMO or Ko-fi
      const fact = (n) => `Fact ${n}.`;
      const stored = async () => (await browser.storage.local.get(KEY))[KEY];
      const settle = async (pred) => {
        for (let i = 0; i < 60; i++) {
          const s = await stored();
          if (s && pred(s)) return s;
          await new Promise((r) => setTimeout(r, 50));
        }
        return (await stored()) || null;
      };
      const snap = () => {
        const rate = box.querySelector('a[data-rate-ask]');
        const tip = box.querySelector('a[data-support]');
        return {
          text: box.querySelector('p') ? box.querySelector('p').textContent : '',
          rate: rate ? rate.href : null, rateLabel: rate ? rate.textContent.trim() : null,
          rateNewTab: rate ? rate.target === '_blank' && rate.rel === 'noopener' : null,
          tip: tip ? tip.href : null,
          buttons: [...box.querySelectorAll('button')].map((b) => b.textContent),
        };
      };
      const out = { slug: self ? self.slug : null, name: self ? self.name : null };
      try {
        await browser.storage.local.remove(KEY);
        out.early = await m.maybeShowMilestone(box, 4, [5, 50], fact);
        out.shown1 = await m.maybeShowMilestone(box, 5, [5, 50], fact);
        out.first = snap();
        box.querySelectorAll('button')[0].click();  // Not now
        out.after1 = await settle((s) => (s.seen || []).includes(5));
        out.hidden1 = box.hidden;
        out.again = await m.maybeShowMilestone(box, 5, [5, 50], fact);
        out.shown2 = await m.maybeShowMilestone(box, 50, [5, 50], fact);
        out.second = snap();
        box.querySelectorAll('button')[1].click();  // Don't ask again
        out.after2 = await settle((s) => s.optOut === true);
        out.afterOptOut = await m.maybeShowMilestone(box, 500, [5, 50, 500], fact);
        // Someone who saw a tip card under an older version: no rating ask recorded yet.
        await browser.storage.local.set({ [KEY]: { seen: [5], optOut: false } });
        out.shown3 = await m.maybeShowMilestone(box, 50, [5, 50], fact);
        out.third = snap();
        const link = box.querySelector('a[data-rate-ask]');
        if (link) link.click();
        out.after3 = await settle((s) => s.rateAsked === true && (s.seen || []).includes(50));
      } finally {
        if (saved === undefined) await browser.storage.local.remove(KEY);
        else await browser.storage.local.set({ [KEY]: saved });
        box.remove();
      }
      return out;
    """)
    out = out if isinstance(out, dict) else {"error": out}
    amo = "https://addons.mozilla.org/firefox/addon/%s/" % out.get("slug")
    first, second, third = (out.get(k) or {} for k in ("first", "second", "third"))
    check("thank-you card: nothing before the first milestone", out.get("early") is False, out.get("error") or out.get("early"))
    check("thank-you card: the first one a user ever gets asks for a rating, not a tip",
          out.get("shown1") is True and bool(out.get("slug")) and first.get("rate") == amo and first.get("rateNewTab") is True
          and first.get("tip") is None and first.get("rateLabel") == "\u2605 Rate %s" % out.get("name")
          and first.get("text") == "Fact 5. It's free, with no ads and no tracking. If it's useful to you, a rating on Firefox Add-ons helps other people find it."
          and first.get("buttons") == ["Not now", "Don't ask again"], first)
    check("thank-you card: 'Not now' closes it and that milestone never comes back",
          out.get("hidden1") is True and 5 in ((out.get("after1") or {}).get("seen") or [])
          and (out.get("after1") or {}).get("rateAsked") is True and out.get("again") is False, (out.get("after1"), out.get("again")))
    check("thank-you card: the next milestone asks for a tip on Ko-fi",
          out.get("shown2") is True and second.get("tip") == "https://ko-fi.com/carcer7378" and second.get("rate") is None
          and second.get("text") == "Fact 50. It's free, with no ads and no tracking. If that's worth a coffee, tips keep it maintained.", second)
    check("thank-you card: 'Don't ask again' is final",
          (out.get("after2") or {}).get("optOut") is True and out.get("afterOptOut") is False, (out.get("after2"), out.get("afterOptOut")))
    check("thank-you card: someone who saw a tip card under an older version is asked to rate once",
          out.get("shown3") is True and third.get("rate") == amo and third.get("tip") is None
          and (out.get("after3") or {}).get("rateAsked") is True and 50 in ((out.get("after3") or {}).get("seen") or []), (third, out.get("after3")))


def main():
    os.environ.setdefault("SE_AVOID_STATS", "true")  # Selenium Manager: no usage ping
    names = [a for a in sys.argv[1:] if a in SESSIONS] or list(SESSIONS)
    unpacked = unpack_build()
    srv = Server(PORT)
    try:
        for name in names:
            print(f"--- {name}", flush=True)
            try:
                SESSIONS[name](unpacked, srv)
            except Exception as e:  # noqa: BLE001
                check(f"{name}: session ran to the end", False, repr(e)[:300])
    finally:
        srv.stop()
        shutil.rmtree(unpacked, ignore_errors=True)
        failed = [n for n, ok in results if not ok]
        print(f"\n{len(results) - len(failed)}/{len(results)} passed")
        if failed:
            print("FAILED: " + ", ".join(failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    assert ADDON_ID
    main()
