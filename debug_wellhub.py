"""
Diagnostic: open Wellhub welcome page, screenshot it, and print all
clickable elements (links + buttons) so we can find the right selectors.
"""
import os
from pathlib import Path

for line in Path(".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
    )
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    page = ctx.new_page()

    print("Navigating to login URL...")
    page.goto("https://gympass.com/us/people/sign-in", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(3_000)

    page.screenshot(path="debug_welcome.png", timeout=0, type="jpeg")
    print(f"Screenshot saved. Current URL: {page.url}")

    print("\n=== All links ===")
    for el in page.query_selector_all("a"):
        try:
            text = el.inner_text().strip()[:60]
            href = el.get_attribute("href") or ""
            if text:
                print(f"  <a> '{text}' → {href}")
        except Exception:
            pass

    print("\n=== All buttons ===")
    for el in page.query_selector_all("button"):
        try:
            text = el.inner_text().strip()[:60]
            typ  = el.get_attribute("type") or ""
            if text:
                print(f"  <button type={typ}> '{text}'")
        except Exception:
            pass

    print("\n=== Inputs ===")
    for el in page.query_selector_all("input"):
        try:
            typ  = el.get_attribute("type") or ""
            name = el.get_attribute("name") or el.get_attribute("placeholder") or ""
            print(f"  <input type={typ} name/placeholder='{name}'>")
        except Exception:
            pass

    browser.close()
    print("\nDone — check debug_welcome.png")
