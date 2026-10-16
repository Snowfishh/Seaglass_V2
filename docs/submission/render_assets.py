"""Build the cover SVGs from their source and render the committed submission SVGs to PNG.

The cover source (cover-16x9.src.svg) names its fonts as FONT:<file> placeholders. The build
embeds the app's own OFL fonts from src/aspire_brain/web/static/fonts as data URIs, so the
generated SVGs render the same in any viewer, and writes one SVG per cover width.

Run with a local Python environment containing Playwright and its Chromium browser.
No credentials, network requests or application database are used.
"""

import base64
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

SUBMISSION = Path(__file__).resolve().parent
FONTS = SUBMISSION.parents[1] / "src" / "aspire_brain" / "web" / "static" / "fonts"
COVER_SOURCE = "cover-16x9.src.svg"
COVERS = (("cover-16x9.svg", 380), ("cover-16x9-384x216.svg", 384))
TARGETS = (
    ("cover-16x9.svg", "cover-16x9-380x216.png", 380, 216, 1),
    ("cover-16x9.svg", "cover-16x9-760x432.png", 380, 216, 2),
    ("cover-16x9-384x216.svg", "cover-16x9-384x216.png", 384, 216, 1),
    ("cover-16x9-384x216.svg", "cover-16x9-768x432.png", 384, 216, 2),
    ("architecture-trust-boundary.svg", "architecture-trust-boundary.png", 1600, 1200, 2),
)


def _font_uri(match):
    data = base64.b64encode((FONTS / match.group(1)).read_bytes()).decode("ascii")
    return f"url(data:font/ttf;base64,{data})"


def build_covers():
    source = (SUBMISSION / COVER_SOURCE).read_text(encoding="utf-8")
    source = re.sub(r"<!-- Source for .*?-->\n", "", source, count=1, flags=re.S)
    source = re.sub(r"url\(FONT:([\w.-]+)\)", _font_uri, source)
    for output, width in COVERS:
        svg = source.replace('width="384"', f'width="{width}"', 1)
        (SUBMISSION / output).write_text(svg, encoding="utf-8")
        print(f"{output}: built from {COVER_SOURCE}")


def main():
    build_covers()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for source, output, width, height, scale in TARGETS:
            context = browser.new_context(
                viewport={"width": width, "height": height}, device_scale_factor=scale,
            )
            # The SVGs are standalone. Block accidental external resources during rendering.
            context.route("http://**/*", lambda route: route.abort())
            context.route("https://**/*", lambda route: route.abort())
            page = context.new_page()
            page.goto((SUBMISSION / source).as_uri())
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(SUBMISSION / output))
            print(f"{output}: {width * scale}x{height * scale}")
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
