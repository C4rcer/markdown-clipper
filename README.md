# Excerpt: Markdown Web Clipper

Firefox add-on (desktop) that turns the article you are reading, or just the
text you selected, into clean Markdown. Copy it or save it as a `.md` file,
with optional front matter so clips drop straight into Obsidian or another
notes app. Free, every feature unlocked, no ads, no tracking, optional Ko-fi tip.

Why this one: MarkDownload has 11k daily users and a 4.9 star rating on AMO but
has not been updated since 2022-09, and it asks for access to every website at
install. The other big one, Obsidian Web Clipper (68k, active), is built around
one notes app and also asks for all sites. Excerpt asks for no site access at
all: it reads a page only when you click it there.

Separate from YouTube/Twitch Enhancer on purpose: YTE only runs on youtube.com
and twitch.tv and has no clipping or Markdown features, and a clipper has to
work on every site.

Desktop only: see [Android](#android).

## Features

- **Article**: the readable part of the page (Mozilla Readability, the engine
  behind Firefox Reader View), without menus, sidebars, ads and footers.
- **Selection**: only what you selected. Cuts out of a code block, a list or a
  table keep their shape (a fenced block with its language, the original list
  numbers, a Markdown table). Dragging across table cells works too.
- **Whole page**: everything visible, nothing hidden.
- **Markdown**: headings, nested and task lists, links, images (as links to the
  picture on the web), fenced code with the language when the page names it,
  tables (with colspan and rowspan), quotes, strikethrough, definition lists.
  Content inside web components (shadow DOM, open or closed) is included.
- **Copy or save**: the popup shows an editable preview with word and character
  counts. Save writes `<page title>.md`, with a name that is safe on Windows,
  macOS, Linux and in Obsidian links.
- **No popup needed**: right-click a page ("Clip page as Markdown") or a
  selection ("Clip selection as Markdown"), or press `Alt+Shift+M` (selection
  if there is one, else the article). Options say whether those copy or save.
  A small confirmation shows in the corner of the page for two seconds.
- **Front matter**: off by default. A template you can edit, with `{title}`,
  `{url}`, `{date}`, `{time}`, `{datetime}`, `{author}`, `{site}`,
  `{description}`, `{published}`. Inside a `---` block, values with quotes,
  colons or `#` are quoted or escaped so the YAML stays valid.
- **Options**: heading style (`#` or underlined), bullet (`-`, `*`, `+`), links
  inline or numbered references, keep images, start with the title as a heading.

## Privacy and permissions

- `activeTab`, `scripting`, `storage`, `menus`. No host permissions, so Firefox
  shows no permission prompt at install, and the add-on can not see any page
  until the user clicks its toolbar button, its menu entry or its shortcut there.
- No `clipboardWrite` and no `downloads` permission: both turned out not to be
  needed (see below).
- All work happens on a detached copy of the page (`document.cloneNode(true)`),
  which loads nothing and runs nothing: the live page is never changed and no
  image or other request goes to the site (the E2E checks both).
- `data_collection_permissions: none`. No network requests at all.

## How it works

1. A click (popup, menu or shortcut) makes the background inject
   `vendor/Readability.js`, `vendor/turndown.js`, `content/markdown.js` and
   `content/clip.js` into the tab (`scripting.executeScript`).
2. `clip.js` copies the page, shadow trees included, and marks in the copy what
   is hidden on the real page (`checkVisibility()` on the real twin of each node).
3. Article mode runs Readability on the copy; selection mode maps the selected
   ranges onto the copy (`getComposedRanges` for ranges that cross a component).
4. `markdown.js` tidies the result (absolute links, lazy-loaded image addresses,
   line-number gutters and copy buttons next to code, heading anchor links) and
   converts it with Turndown plus its own rules for headings, lists, code,
   links, images, tables and quotes.

Things measured in Firefox 147 while building it:

- **Clipboard without `clipboardWrite`**: the background page may write to the
  clipboard for about 5 seconds after a menu click or a shortcut. A write
  started at once with `ClipboardItem({"text/plain": promise})` still lands when
  the text arrives later (tested with 7 s), so a long article never misses the
  window. A content script can not do the same after a shortcut (no user
  activation in the page). The popup's Copy button needs no permission either.
- **Saving without `downloads`**: a click on an `<a download>` with a blob URL
  saves the file from the popup, the background page or the content script.
  With "Always ask where to save files" on, the Save dialog gets the right name.
  A save started from the background page opens that dialog for the invisible
  background page (`chrome://extensions/content/dummy.xhtml`) instead of the
  browser window, so the menu and the shortcut save through the page, and only
  fall back to the background on pages served with
  `Content-Security-Policy: sandbox` (those can not start downloads). That
  fallback was only tried with a stand-in file picker, not a real dialog.
- `executeScript` on `about:addons` does not throw: it returns `[null]`. Both
  that and a thrown error are treated as "Firefox keeps add-ons out of here".
- A selection inside a frame from another site can not be read (activeTab is
  for the tab's own site); the menu entry then copies the plain selected text.
- In headless Firefox the popup panel does not take the keyboard focus by
  itself, so the E2E focuses it before pressing Enter. A real window does.

## Third-party code

Shipped unmodified in `src/vendor/`, with their license texts next to them.
Both are plain, unminified release files, so AMO needs no source upload.

| File | Library | Version | Source | License | SHA-256 |
| --- | --- | --- | --- | --- | --- |
| `vendor/Readability.js` | Mozilla Readability | 0.6.0 | `package/Readability.js` from https://registry.npmjs.org/@mozilla/readability/-/readability-0.6.0.tgz (https://github.com/mozilla/readability) | Apache-2.0 | `34dcab3d0832d0019f02990eed6b6124e029e8c32b9f0c6f2550544ff8dff174` |
| `vendor/turndown.js` | Turndown | 7.2.5 | `package/dist/turndown.js` from https://registry.npmjs.org/turndown/-/turndown-7.2.5.tgz (https://github.com/mixmark-io/turndown) | MIT | `f46330e27d6009ecc3b001237e735cf58293772d2a465436a61de6f536b59a81` |

- `vendor/Readability.LICENSE.txt`: the package's `LICENSE.md` notice plus the
  full Apache License 2.0 text from https://www.apache.org/licenses/LICENSE-2.0.txt.
  The package has no NOTICE file.
- `vendor/turndown.LICENSE.txt`: the package's `LICENSE` (MIT, Dom Christie).
  `turndown.js` also keeps the MIT notice of collapse-whitespace (Luc Thevenard)
  that it contains.
- Both licenses allow shipping inside an MPL-2.0 add-on: MPL-2.0 is file-level
  copyleft and lets a "Larger Work" include files under other licenses
  (section 3.3). The two library files stay under their own licenses; only our
  own files are MPL-2.0. Apache-2.0 and MIT only ask that the license and
  copyright notices travel with the files, which they do.
- Turndown 7.2.5 was a week old when vendored (2026-11-04). Its `dist/turndown.js`
  was diffed against 7.2.4: the only change is a faster way of joining output
  (an array instead of string concatenation). Neither file makes network
  requests or uses `eval`.

**Lint**: `web-ext lint` reports 0 errors, 0 notices and 2 warnings, both
`UNSAFE_VAR_ASSIGNMENT` inside `vendor/Readability.js` (lines 1549 and 1928:
Readability resets its own working copy with `innerHTML`). The linter's list of
known libraries contains neither Readability nor Turndown, so it scans them like
our own code. The warnings can only go away by editing the library, which AMO
reviewers would then have to check by hand against the original. Here
Readability only ever runs on a detached copy of the page that has no browsing
context, so nothing it parses can run or load.

## Android

Not listed for Firefox for Android in 0.1.0, and the manifest has no
`gecko_android` block:

- MDN's compatibility data (@mdn/browser-compat-data 8.1.8): `menus` and
  `commands` do not exist on Firefox for Android, so the right-click entries
  and the shortcut can not exist there. The popup, `scripting` and `activeTab`
  do exist.
- Copy and save from the popup might work there, but there was no Android
  device or emulator on the build machine, so it could not be tested. Blob
  downloads from extension pages in particular need a real check.

## Layout

```
src/                       everything that ships
  manifest.json
  background.js            injects the clipper, right-click menu, shortcut, copy/save without the popup
  content/clip.js          reads the page: copy with shadow trees, selection, article, page
  content/markdown.js      tidy + Turndown rules, front matter template, file names
  popup/                   mode switch, editable preview, Copy, Save, front matter toggle
  options/                 Markdown style, front matter template, menu/shortcut action, support
  shared/settings.js       settings defaults and validation (classic script, used everywhere)
  shared/support.*         Ko-fi pill + one-time milestone card (from the template)
  shared/more-addons.*     "More free add-ons" card + rate link (same file in every add-on; set `live: true` as listings are approved)
  vendor/                  Readability, Turndown and their licenses (unmodified)
store-assets/listing.json  AMO listing text, categories, Ko-fi contributions_url, captions
store-assets/screenshots/  1280x800 listing images (made by tests/screenshots.py)
tests/                     real-Firefox E2E, test pages, expected Markdown, screenshot generator
tools/release.py           build / lint / submit / status / contrib / screenshots
```

Storage keys (`browser.storage.local`): `settings` (`headingStyle`, `bullet`,
`linkStyle`, `images`, `titleHeading`, `frontMatter`, `frontMatterTemplate`,
`quickAction`), `stats` (`clips`, for the milestone card after 25 and 250
clips), `supportNudge`.

## Develop and test

```powershell
python tools/release.py lint                 # build + web-ext lint the zip (0 errors, 2 library warnings, 0 notices)
python -m pip install selenium pillow        # once, ideally in a venv, for the tests
python tests/e2e_firefox.py                  # 138 checks in headless Firefox, about 1 min
python tests/e2e_firefox.py main             # one session only: main ask idle
python tests/screenshots.py                  # regenerate store screenshots
```

The E2E installs the extracted built zip, serves `tests/pages/` on
127.0.0.1:8961 and compares the Markdown with `tests/expected/*.md` (and
strings in the test) character for character. Because the add-on only has
`activeTab`, the test goes through Firefox's own UI (geckodriver
`--allow-system-access`): the real toolbar button and popup panel, the real
right-click menu, the real shortcut. Nothing is granted by hand. The clipboard
is read back from Firefox itself (headless Firefox has its own, yours is not
touched) and saved files land in a temp folder.

What it covers: article, whole page and selection output for a page with
headings, nested lists, links, code blocks with and without a language, a
table, a quote, images (lazy-loaded, linked, data: and tracking pixels); eleven
kinds of selection; an edge-case page (escaping, task lists, broken nesting,
tables with spans, captions, layout and nested tables, code gutters and copy
buttons, embeds, hidden content); the options and front matter (YAML quoting of
a title with quotes, colon and `#`); file names; frames from the same and
another site; web components with open, closed and nested shadow trees; a 6000
paragraph article through the shortcut; a strict CSP page; a sandboxed page; an
empty page, a page of links, an SVG file and `about:addons`; the milestone
card; Firefox's "always ask where to save"; and every action with the
background page asleep first (as it usually is in real use).

Manual: `about:debugging#/runtime/this-firefox` → Load Temporary Add-on → `src/manifest.json`.

## Known limits

- Images are links to the picture on the web, not downloaded copies.
- Article mode, like Reader View, ignores the page's style sheets: text the page
  hides with CSS (a closed FAQ answer, a collapsed section, a `<details>` that is
  shut) can show up in an Article clip. Whole page mode leaves out everything
  the reader can not see.
- A selection inside a frame from another site comes as plain text.
- Firefox's own pages (about:, addons.mozilla.org, the PDF viewer, Reader View)
  can not be clipped: Firefox lets no add-on in there.

## Release

Submitted to AMO on 2026-11-11: add-on id 3125202, slug
`excerpt-markdown-web-clipper`, version 0.1.0, waiting for review. gecko id
`excerpt-markdown-clipper@c4rcer`, license MPL-2.0, categories "Feeds, News &
Blogging" and "Web Development", Firefox desktop only. AMO's own validation:
0 errors, 2 warnings (the Readability lines above), 0 notices.

Read back from the API after the submit: the description has its 6 bold
headings and no literal tags, the Ko-fi Contribute link is set, and the 3
screenshots are on the listing at 1280x800 with their captions. The listing
create waited about 5.8 hours on AMO's daily write limit, and the screenshot
upload about 3 more hours.

```powershell
python tools/release.py status                              # review state
python -u tools/release.py submit --notes "What changed"    # later versions
```

Bump `version` in `src/manifest.json` for every later submit. AMO reads the
listing description as Markdown, so `store-assets/listing.json` uses
`**Heading**`. `release.py` only sends the description when it creates the
listing; a later text change needs a PATCH of `description` on
`/addons/addon/<gecko id>/`.
