"""Render the committed submission SVGs without replacing their source templates.

Run with a local Python environment containing Playwright and its Chromium browser.
No credentials, network requests or application database are used.
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

SUBMISSION = Path(__file__).resolve().parent
TARGETS = (
    ("cover-16x9.svg", "cover-16x9-380x216.png", 380, 216, 1),
    ("cover-16x9.svg", "cover-16x9-760x432.png", 380, 216, 2),
    ("cover-16x9-384x216.svg", "cover-16x9-384x216.png", 384, 216, 1),
    ("cover-16x9-384x216.svg", "cover-16x9-768x432.png", 384, 216, 2),
    ("architecture-trust-boundary.svg", "architecture-trust-boundary.png", 1600, 1160, 2),
)


def main():
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
            page.screenshot(path=str(SUBMISSION / output))
            print(f"{output}: {width * scale}x{height * scale}")
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
