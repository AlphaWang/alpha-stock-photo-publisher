#!/usr/bin/env python3
"""
Selector discovery tool for upload automation.
Opens the target platform in a headed browser, lets you navigate/login,
then dumps all interactive form elements found on the current page.

Usage:
  python3 debug_selectors.py shutterstock
  python3 debug_selectors.py px500
"""

import sys
from playwright.sync_api import sync_playwright
from upload.browser import get_context

PLATFORMS = {
    "shutterstock": "https://submit.shutterstock.com/",
    "px500": "https://creatorstudio.500px.com.cn/index",
    "tuchong": "https://contributor.tuchong.com/contribute?category=0",
    "adobestock": "https://contributor.stock.adobe.com/",
    "istock": "https://esp.gettyimages.com/",
}


def dump_elements(page):
    print("\n--- Inputs ---")
    for el in page.locator("input:visible").all():
        attrs = {a: el.get_attribute(a) for a in ["type", "name", "placeholder", "class", "id"] if el.get_attribute(a)}
        print(" ", attrs)

    print("\n--- Textareas ---")
    for el in page.locator("textarea:visible").all():
        attrs = {a: el.get_attribute(a) for a in ["name", "placeholder", "class", "id"] if el.get_attribute(a)}
        print(" ", attrs)

    print("\n--- Buttons ---")
    for el in page.locator("button:visible").all():
        text = el.inner_text().strip()[:60]
        cls = el.get_attribute("class") or ""
        print(f"  [{text!r}] class={cls[:80]!r}")

    print("\n--- File inputs (including hidden) ---")
    for el in page.locator("input[type='file']").all():
        attrs = {a: el.get_attribute(a) for a in ["name", "accept", "class", "id"] if el.get_attribute(a)}
        print(" ", attrs)

    print("\n--- Clickable image cards (li / [role] / [data-*]) ---")
    for el in page.locator("li, [role='gridcell'], [role='listitem'], [role='button']:visible").all():
        cls = el.get_attribute("class") or ""
        role = el.get_attribute("role") or ""
        data_attrs = {k: el.get_attribute(k) for k in ["data-id", "data-testid", "data-asset-id"] if el.get_attribute(k)}
        if cls or role or data_attrs:
            print(f"  tag={el.evaluate('el=>el.tagName')} role={role!r} class={cls[:80]!r} data={data_attrs}")

    print("\n--- Thumbnail containers (large imgs in left panel) ---")
    results = page.evaluate("""() => {
        const thumbs = [...document.querySelectorAll('img')].filter(img => {
            const r = img.getBoundingClientRect();
            return r.width >= 60 && r.height >= 60 && r.left < window.innerWidth * 0.6;
        });
        return thumbs.map(img => {
            const p = img.closest('[class]') || img.parentElement;
            return {
                imgAlt: img.alt,
                parentTag: p ? p.tagName : '',
                parentClass: p ? (p.className || '').slice(0, 120) : '',
                parentTitle: p ? (p.title || '') : '',
            };
        });
    }""")
    for r in results:
        print(f"  <{r['parentTag']} class={r['parentClass']!r} title={r['parentTitle']!r}> img alt={r['imgAlt']!r}")


def main():
    platform = sys.argv[1] if len(sys.argv) > 1 else "shutterstock"
    if platform not in PLATFORMS:
        sys.exit(f"Unknown platform: {platform}. Choices: {', '.join(PLATFORMS)}")

    url = PLATFORMS[platform]

    with sync_playwright() as pw:
        ctx = get_context(platform, pw)
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")

        while True:
            print(f"\nCurrent URL: {page.url}")
            print("Commands: [d]ump elements  [r]efresh dump  [q]uit")
            cmd = input("> ").strip().lower()
            if cmd in ("q", "quit"):
                break
            elif cmd in ("d", "r", "dump", "refresh"):
                dump_elements(page)
            else:
                print("Navigate the browser manually, then dump when ready.")

        ctx.close()


if __name__ == "__main__":
    main()
