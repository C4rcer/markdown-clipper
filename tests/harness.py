"""Shared pieces of the Excerpt tests: a local web server and one headless Firefox with the add-on.

Used by tests/e2e_firefox.py and tests/screenshots.py. Every browser runs
headless and muted. The add-on only has activeTab, so the tests reach it the
way a user does (geckodriver --allow-system-access): the real toolbar button,
the real right-click menu, the real keyboard shortcut. Nothing is granted by hand.
"""
import http.server
import json
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / "tests" / "pages"
ADDON_ID = "excerpt-markdown-clipper@c4rcer"
WIDGET_ID = "excerpt-markdown-clipper_c4rcer-browser-action"
UUID = "0b7d3c52-51c4-4c8e-9a61-e8ce4b7c11b5"
EXT = f"moz-extension://{UUID}"
FIREFOX = r"C:\Program Files\Mozilla Firefox\firefox.exe"
STRICT_CSP = "default-src 'none'; img-src 'self'; style-src 'nonce-excerpt-test'; script-src 'nonce-excerpt-test'"


def wait(fn, timeout=8.0, step=0.1):
    """Poll fn until it returns something truthy; returns the last value either way."""
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = fn()
            if last:
                return last
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(step)
    return last


BIG_SENTENCE = ("The tide table for this harbor lists a high water and a low water for every day of the year, "
                "and each line of it was worked out long before anyone needed it.")


def big_page(n):
    """A very long article: n paragraphs, each with a link, to see how the clipper copes."""
    paragraphs = "\n".join(
        f'<p>Paragraph {i}. {BIG_SENTENCE} See <a href="/note/{i}">note {i}</a>.</p>' for i in range(1, n + 1))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>A very long article</title></head>'
            f"<body><article><h1>A very long article</h1>\n{paragraphs}\n</article></body></html>")


def big_markdown(n, base):
    lines = ["# A very long article"]
    lines += [f"Paragraph {i}. {BIG_SENTENCE} See [note {i}]({base}/note/{i})." for i in range(1, n + 1)]
    return "\n\n".join(lines) + "\n"


class Server:
    """Serves tests/pages on 127.0.0.1 and remembers every path that was asked for."""

    def __init__(self, port, directory=PAGES):
        self.port = port
        self.requests = []
        outer = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(directory), **kwargs)

            def log_message(self, *args):
                pass

            def do_GET(self):
                outer.requests.append(self.path)
                if self.path.startswith("/big.html"):
                    body = big_page(int(self.path.split("n=")[1])).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                super().do_GET()

            def end_headers(self):
                if "csp=strict" in self.path:
                    self.send_header("Content-Security-Policy", STRICT_CSP)
                if "csp=sandbox" in self.path:
                    self.send_header("Content-Security-Policy", "sandbox")
                self.send_header("Cache-Control", "no-store")
                super().end_headers()

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, path, host="127.0.0.1"):
        return f"http://{host}:{self.port}/{path}"

    def stop(self):
        self.httpd.shutdown()


def unpack_build():
    """Extract the newest built zip. Geckodriver must get a folder: it installs a
    zip from a temp copy that it deletes, and scripts then fail to load."""
    zips = sorted((ROOT / "dist").glob("*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        raise SystemExit("build first: python tools/release.py build")
    out = Path(tempfile.mkdtemp(prefix="excerpt-build-"))
    with zipfile.ZipFile(zips[-1]) as z:
        z.extractall(out)
    return out


class Fx:
    """One headless Firefox with the built add-on: a window with the page under test,
    and a second window on an extension page (for the WebExtension API and the popup in a tab)."""

    def __init__(self, unpacked, prefs=None, hosts=()):
        self.downloads = Path(tempfile.mkdtemp(prefix="excerpt-dl-"))
        opts = Options()
        opts.binary_location = FIREFOX
        opts.add_argument("-headless")
        opts.set_preference("media.volume_scale", "0.0")
        opts.set_preference("extensions.webextensions.uuids", json.dumps({ADDON_ID: UUID}))
        opts.set_preference("browser.download.folderList", 2)
        opts.set_preference("browser.download.dir", str(self.downloads))
        opts.set_preference("browser.download.useDownloadDir", True)
        opts.set_preference("browser.download.alwaysOpenPanel", False)
        if hosts:
            opts.set_preference("network.dns.localDomains", ",".join(hosts))
        for k, v in (prefs or {}).items():
            opts.set_preference(k, v)
        self.d = webdriver.Firefox(options=opts, service=Service(service_args=["--allow-system-access"]))
        self.d.set_window_size(1280, 900)
        self.d.execute("INSTALL_ADDON", {"path": str(unpacked), "temporary": True})
        time.sleep(1.0)
        self.page = self.d.current_window_handle
        self.d.switch_to.new_window("window")
        self.ext = self.d.current_window_handle
        self.d.get(f"{EXT}/options/options.html")
        self.to_page()

    def quit(self):
        try:
            self.d.quit()
        finally:
            shutil.rmtree(self.downloads, ignore_errors=True)

    # ---- windows
    def to_page(self):
        if self.d.current_window_handle != self.page:
            self.d.switch_to.window(self.page)
        self.d.switch_to.default_content()

    def to_ext(self):
        if self.d.current_window_handle != self.ext:
            self.d.switch_to.window(self.ext)

    def open(self, url):
        self.to_page()
        self.d.get(url)

    def js(self, script, *args):
        self.to_page()
        return self.d.execute_script(script, *args)

    def api(self, code):
        """Run async code with the WebExtension API, on the extension page."""
        self.to_ext()
        return self.d.execute_async_script(
            "const done = arguments[arguments.length - 1];"
            f"(async () => {{ {code} }})().then(done, (e) => done('ERR ' + e));")

    def chrome(self, script, *args):
        """Run privileged code in the browser window that holds the page under test."""
        self.to_page()
        with self.d.context("chrome"):
            return self.d.execute_script(script, *args)

    # ---- storage
    def store(self):
        return self.api("return await browser.storage.local.get();")

    def settings(self, **patch):
        """Change settings the way the options page does."""
        return self.api(f"return await ExcerptSettings.save({json.dumps(patch)});")

    def clips(self):
        return (self.store().get("stats") or {}).get("clips", 0)

    def page_tab_id(self):
        return self.api("""
          const me = await browser.tabs.getCurrent();
          const t = (await browser.tabs.query({ active: true })).find((x) => x.windowId !== me.windowId);
          return t ? t.id : null;""")

    # ---- clipboard (headless Firefox has its own: the real one is never touched)
    def clipboard(self):
        return self.chrome("""
          try {
            const t = Cc["@mozilla.org/widget/transferable;1"].createInstance(Ci.nsITransferable);
            t.init(null);
            t.addDataFlavor("text/plain");
            Services.clipboard.getData(t, Ci.nsIClipboard.kGlobalClipboard, window.browsingContext.currentWindowContext);
            const out = {};
            t.getTransferData("text/plain", out);
            return out.value.QueryInterface(Ci.nsISupportsString).data;
          } catch (e) { return null; }
        """)

    def clear_clipboard(self):
        self.chrome("Services.clipboard.emptyClipboard(Ci.nsIClipboard.kGlobalClipboard);")

    def copied(self, timeout=8.0):
        """Wait for text on the clipboard and return it (line ends as the page had them)."""
        got = wait(self.clipboard, timeout)
        return got.replace("\r\n", "\n") if isinstance(got, str) else None

    # ---- browser UI, the way a user reaches it
    def shortcut(self):
        self.to_page()
        with self.d.context("chrome"):
            ActionChains(self.d).key_down(Keys.ALT).key_down(Keys.SHIFT).send_keys("m") \
                .key_up(Keys.SHIFT).key_up(Keys.ALT).perform()

    def press(self, key):
        """A real key press in the browser window (reaches an open popup panel)."""
        self.to_page()
        with self.d.context("chrome"):
            ActionChains(self.d).send_keys(key).perform()

    def click_toolbar_button(self):
        return self.chrome("""
          const item = document.getElementById(arguments[0]);
          if (!item) return "no toolbar item";
          const where = item.closest("#nav-bar") ? "nav-bar" : (item.closest("panel, toolbar") || {}).id;
          (item.querySelector(".unified-extensions-item-action-button") || item).click();
          return where;
        """, WIDGET_ID)

    def panel_url(self):
        return self.chrome("""
          const b = document.querySelector("browser.webextension-popup-browser");
          return b && b.currentURI ? b.currentURI.spec : null;
        """)

    def panel_eval(self, expression):
        """Read something from the real popup panel (its document is `content.document`)."""
        self.chrome("""
          const b = document.querySelector("browser.webextension-popup-browser");
          window.__excerptPanelValue = undefined;
          b.messageManager.addMessageListener("excerpt-test", function once(m) {
            b.messageManager.removeMessageListener("excerpt-test", once);
            window.__excerptPanelValue = { value: m.data };
          });
          b.messageManager.loadFrameScript("data:," + encodeURIComponent(
            "sendAsyncMessage('excerpt-test', (() => { try { return " + arguments[0] + "; } catch (e) { return 'ERR ' + e; } })());"), false);
        """, expression)
        got = wait(lambda: self.chrome("return window.__excerptPanelValue"), 4)
        return got["value"] if isinstance(got, dict) else None

    def focus_panel(self):
        """Put the keyboard focus in the open popup. A real window does this by itself
        when the popup opens; a headless one has no active window and leaves it out."""
        self.chrome('document.querySelector("browser.webextension-popup-browser").focus();')
        time.sleep(0.2)

    def close_panel(self):
        self.chrome("""
          const b = document.querySelector("browser.webextension-popup-browser");
          const p = b && b.closest("panel");
          if (p) p.hidePopup();
        """)

    def has_active_tab(self):
        return self.chrome(
            "return WebExtensionPolicy.getByID(arguments[0]).extension.tabManager.hasActiveTabPermission(gBrowser.selectedTab);",
            ADDON_ID)

    def menu_labels(self, css, frame=None):
        """Right-click an element and return the add-on's entries in the context menu, then close it."""
        return self._menu(css, None, frame)

    def menu_click(self, css, label, frame=None):
        """Right-click an element and choose one of the add-on's menu entries."""
        return self._menu(css, label, frame)

    def _menu(self, css, label, frame):
        self.to_page()
        if frame:
            self.d.switch_to.frame(self.d.find_element(By.CSS_SELECTOR, frame))
        ActionChains(self.d).context_click(self.d.find_element(By.CSS_SELECTOR, css)).perform()
        self.d.switch_to.default_content()
        wait(lambda: self.chrome("return document.getElementById('contentAreaContextMenu').state") == "open", 4)
        return self.chrome("""
          const cm = document.getElementById("contentAreaContextMenu");
          const mine = [...cm.querySelectorAll("menuitem")].filter((i) => !i.hidden && /as Markdown$/.test(i.label || ""));
          const labels = mine.map((i) => i.label);
          const item = mine.find((i) => i.label === arguments[0]);
          if (item) item.doCommand();
          cm.hidePopup();
          return arguments[0] ? !!item : labels;
        """, label)

    # ---- the page
    def toast(self):
        """Text of the confirmation the add-on shows in the page, or None."""
        return self.js("const t = document.querySelector('[data-excerpt-toast]'); return t ? t.textContent : null;")

    def select(self, script):
        """Run JS that builds a selection (the variable `sel` is the page's Selection, already emptied)."""
        self.js("const sel = getSelection(); sel.removeAllRanges();" + script)

    def badge(self):
        return self.api("return await browser.action.getBadgeText({});")

    def saved(self, name, timeout=8.0):
        """Wait for a downloaded file and return its text, or None."""
        path = self.downloads / name

        def ready():
            return path.exists() and not (self.downloads / (name + ".part")).exists() and path.stat().st_size > 0
        if not wait(ready, timeout):
            return None
        return path.read_bytes().decode("utf-8")

    def saved_names(self):
        return sorted(p.name for p in self.downloads.iterdir())

    # ---- the popup, opened as a tab in the second window and pointed at the page
    def popup(self, wait_ready=True):
        tab_id = self.page_tab_id()
        self.to_ext()
        self.d.get(f"{EXT}/popup/popup.html?tab={tab_id}")
        if wait_ready:
            wait(lambda: self.d.find_element(By.ID, "copy").is_enabled() or self.d.find_element(By.ID, "error").is_displayed(), 10)
        return tab_id

    def preview(self):
        self.to_ext()
        return self.d.find_element(By.ID, "preview").get_attribute("value")

    def popup_mode(self, mode):
        """Click a mode button in the popup and wait until the preview shows that mode."""
        self.to_ext()
        self.d.find_element(By.CSS_SELECTOR, f'#mode button[data-mode="{mode}"]').click()
        wait(lambda: self.d.find_element(By.CSS_SELECTOR, f'#mode button[data-mode="{mode}"]').get_attribute("aria-checked") == "true"
             and (self.d.find_element(By.ID, "copy").is_enabled() or self.d.find_element(By.ID, "error").is_displayed()), 10)
        time.sleep(0.15)
        return self.preview()
