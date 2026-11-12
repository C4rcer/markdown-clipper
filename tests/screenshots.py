"""Capture the AMO listing screenshots (1280x800) of Excerpt in a real Firefox.

  python tools/release.py build
  python tests/screenshots.py          (needs selenium + pillow)

Writes store-assets/screenshots/{1-article,2-selection,3-options}.png. The
backdrop is tests/demo/how-tidal-clocks-work.html (a made-up magazine page);
nothing in tests/ ships in the add-on. The popup is the real one, opened in a
tab so it can be photographed, and pointed at the demo page after the real
toolbar button has given the add-on that tab.
"""
import os
import shutil
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from selenium.webdriver.common.by import By

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import EXT, ROOT, Fx, Server, unpack_build, wait  # noqa: E402

DEMO_HOST = "harbor-review.example.com"  # mapped to 127.0.0.1 via network.dns.localDomains
DEMO_PAGE = "how-tidal-clocks-work.html"
OUT = ROOT / "store-assets" / "screenshots"
W, H = 1280, 800
# 1.5 device pixels per CSS pixel. Firefox can only do scales where 60 / scale is a
# whole number, so 1.5 is exact (853 x 533 CSS pixels) where 1.6 would come out as 1.579.
DPR = 1.5
PAPER = (251, 250, 246)


def fit(img):
    """Crop/pad a capture to exactly 1280x800."""
    canvas = Image.new("RGB", (W, H), PAPER)
    canvas.paste(img.convert("RGB").crop((0, 0, min(W, img.width), min(H, img.height))), (0, 0))
    return canvas


def card(img, radius=18, scale=1.0):
    """Rounded corners and a soft drop shadow around a capture."""
    img = img.convert("RGBA")
    if scale != 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius, fill=255)
    pad = 40
    out = Image.new("RGBA", (img.width + pad * 2, img.height + pad * 2), (0, 0, 0, 0))
    shadow = Image.new("L", out.size, 0)
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + 8, pad + img.width, pad + img.height + 8), radius, fill=130)
    out.putalpha(shadow.filter(ImageFilter.GaussianBlur(18)))
    out.paste(img, (pad, pad), mask)
    return out, pad


def dimmed(img, alpha):
    base = fit(img).convert("RGBA")
    return Image.alpha_composite(base, Image.new("RGBA", base.size, (16, 36, 42, alpha)))


def main():
    os.environ.setdefault("SE_AVOID_STATS", "true")
    try:
        srv = Server(80, directory=ROOT / "tests" / "demo")  # port 80 keeps the address in the front matter clean
    except OSError:
        srv = Server(8942, directory=ROOT / "tests" / "demo")
    port = "" if srv.port == 80 else f":{srv.port}"
    url = f"http://{DEMO_HOST}{port}/{DEMO_PAGE}"
    unpacked = unpack_build()
    fx = Fx(unpacked, hosts=[DEMO_HOST], prefs={
        "layout.css.devPixelsPerPx": str(DPR),
        "ui.systemUsesDarkTheme": 0,
        "layout.css.prefers-color-scheme.content-override": 1,  # light
    })
    d = fx.d
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        fx.to_page()
        cw, ch = round(W / DPR), round(H / DPR)
        outer = [cw, ch + 90]
        inner = None
        for _ in range(6):  # grow the window until the page area is 853x533 CSS px (1280x800 on screen)
            d.set_window_size(*outer)
            time.sleep(0.3)
            inner = d.execute_script("return [innerWidth, innerHeight]")
            if inner == [cw, ch]:
                break
            outer = [outer[0] + cw - inner[0], outer[1] + ch - inner[1]]
        print("viewport:", inner, "window:", outer, "page:", url)

        def page_shot(name):
            fx.to_page()
            path = OUT / name
            d.save_screenshot(str(path))
            return Image.open(path)

        def popup_shot(name):
            fx.popup()
            time.sleep(0.5)
            path = OUT / name
            d.find_element(By.TAG_NAME, "body").screenshot(str(path))
            return Image.open(path)

        def compose(backdrop, popup, name):
            scale = min(1.0, (H - 28) / popup.height)
            shadowed, pad = card(popup, radius=14, scale=scale)
            shot = backdrop.copy()
            shot.alpha_composite(shadowed, (W - shadowed.width + pad - 30, (H - (shadowed.height - 2 * pad)) // 2 - pad))
            shot.convert("RGB").save(OUT / name)

        fx.open(url)
        time.sleep(0.8)
        fx.click_toolbar_button()  # the real button: this is what gives the add-on the tab
        wait(fx.panel_url, 5)
        time.sleep(0.5)
        fx.close_panel()
        fx.to_ext()
        d.set_window_size(outer[0], 1100)

        # ---- 1: the article as Markdown, front matter on
        fx.settings(frontMatter=True)
        top = page_shot("_top.png")
        compose(dimmed(top, 40), popup_shot("_popup1.png"), "1-article.png")

        # ---- 2: only the selected part: a heading, a paragraph and a table
        fx.settings(frontMatter=False)
        fx.js("document.getElementById('reading').scrollIntoView();")
        fx.select("""
          const r = document.createRange(); r.setStartBefore(document.getElementById('drift'));
          r.setEndAfter(document.getElementById('drift-table')); sel.addRange(r);""")
        time.sleep(0.4)
        middle = page_shot("_middle.png")
        compose(dimmed(middle, 40), popup_shot("_popup2.png"), "2-selection.png")
        fx.select("")

        # ---- 3: the settings that shape the Markdown
        fx.settings(frontMatter=True)
        fx.to_ext()
        d.get(f"{EXT}/options/options.html")
        wait(lambda: d.find_element(By.ID, "template").get_attribute("value") != "", 4)
        d.execute_script(
            "const st = document.createElement('style');"
            "st.textContent = '.page { max-width: 420px; padding: 0 } .card-block { margin: 0 }';"
            "document.head.append(st);")
        time.sleep(0.4)
        blocks = d.find_elements(By.CSS_SELECTOR, ".card-block")
        blocks[0].screenshot(str(OUT / "_style.png"))
        blocks[1].screenshot(str(OUT / "_front.png"))
        style_img, front_img = Image.open(OUT / "_style.png"), Image.open(OUT / "_front.png")
        gap = 28
        scale = min(1.0, (H - 56) / max(style_img.height, front_img.height), (W - 80 - gap) / (style_img.width + front_img.width))
        left, pad = card(style_img, radius=16, scale=scale)
        right, _ = card(front_img, radius=16, scale=scale)
        total = (left.width - 2 * pad) + gap + (right.width - 2 * pad)
        x = (W - total) // 2
        shot = dimmed(top, 150)
        shot.alpha_composite(left, (x - pad, (H - (left.height - 2 * pad)) // 2 - pad))
        shot.alpha_composite(right, (x + (left.width - 2 * pad) + gap - pad, (H - (right.height - 2 * pad)) // 2 - pad))
        shot.convert("RGB").save(OUT / "3-options.png")
        fx.settings(frontMatter=False)
    finally:
        fx.quit()
        srv.stop()
        shutil.rmtree(unpacked, ignore_errors=True)
        for tmp in OUT.glob("_*.png"):
            tmp.unlink()
    for p in sorted(OUT.glob("*.png")):
        print(p.relative_to(ROOT), Image.open(p).size)


if __name__ == "__main__":
    main()
