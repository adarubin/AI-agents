"""Playwright Chromium factory for the applier. No LinkedIn session/cookie handling is needed --
Greenhouse and Lever forms are ordinary public application pages."""

from __future__ import annotations

from contextlib import contextmanager

from playwright.sync_api import Browser, BrowserContext, sync_playwright

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@contextmanager
def browser_context(headless: bool = True):
    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(headless=headless)
        context: BrowserContext = browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="Asia/Jerusalem",
        )
        try:
            yield context
        finally:
            context.close()
            browser.close()
