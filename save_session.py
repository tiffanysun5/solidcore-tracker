"""
One-time session capture: opens a real browser, lets you log in manually,
then saves the cookies to session.json for all future automated runs.

Run this once:
  python3 save_session.py

The session.json is gitignored — it lives only on your machine.
"""
import json, time
from pathlib import Path
from playwright.sync_api import sync_playwright

SESSION_FILE = Path("session.json")

print("Opening Wellhub login page...")
print("→ Log in normally in the browser window that appears.")
print("→ Once you see the Wellhub home screen, come back here and press Enter.")
print()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800},
    )
    page = ctx.new_page()
    page.goto("https://gympass.com/us/people/sign-in", wait_until="domcontentloaded")

    input("Press Enter once you're fully logged in and see the Wellhub home screen... ")

    cookies = ctx.cookies()
    storage = ctx.storage_state()
    SESSION_FILE.write_text(json.dumps(storage, indent=2))
    print(f"\n✓ Session saved to {SESSION_FILE} ({len(cookies)} cookies)")
    print("  You won't need to log in again until the session expires.")
    browser.close()
