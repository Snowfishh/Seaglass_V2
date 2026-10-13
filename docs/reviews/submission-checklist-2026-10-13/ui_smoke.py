"""Isolated browser check of the theme/UI refresh; creates only a disposable synthetic runtime."""
import json
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))

import uvicorn
from playwright.sync_api import sync_playwright

from aspire_brain.config import Settings
from aspire_brain.db import Database
from aspire_brain.main import create_app

runtime = Path(tempfile.mkdtemp(prefix='seaglass-ui-', dir='/private/tmp'))
settings = Settings(db_path=runtime / 'brain.db', session_secret=secrets.token_hex(32),
                    audit_key=secrets.token_bytes(32), payload_key=secrets.token_bytes(32),
                    demo_mode=True)
db = Database(settings.db_path)
db.initialize()
db.seed(ROOT / 'data/demo/manifest.json', ROOT / 'data/demo/principals.json')
server = uvicorn.Server(uvicorn.Config(create_app(settings), host='127.0.0.1', port=0,
                                      access_log=False, log_level='error'))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
deadline = time.monotonic() + 10
while not server.started:
    if time.monotonic() > deadline:
        raise RuntimeError('Local test server did not start')
    time.sleep(.05)
port = server.servers[0].sockets[0].getsockname()[1]
origin = f'http://127.0.0.1:{port}'
FOOTER = 'Human review remains required'
checks = {}
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 900})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/')
                      else route.abort())
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)

        # Without a persona, the case note links to the travel-policy demo rather than '/'.
        page.goto(origin + '/cases')
        page.locator('[data-case=case_1] button').click()
        note = page.locator('[data-case=case_1] .case-note a')
        note.wait_for()
        assert note.get_attribute('href') == '/ask'
        assert FOOTER in page.locator('footer').inner_text()
        checks['case_note_links_to_ask'] = True

        # Theme toggle applies dark mode and the stored preference survives navigation.
        light = page.evaluate('getComputedStyle(document.body).backgroundColor')
        page.locator('#theme-toggle').click()
        assert page.evaluate('document.documentElement.dataset.theme') == 'dark'
        page.goto(origin + '/ask')
        assert page.evaluate('document.documentElement.dataset.theme') == 'dark'
        assert page.evaluate('getComputedStyle(document.body).backgroundColor') != light
        assert page.locator('#theme-toggle').get_attribute('aria-pressed') == 'true'
        assert FOOTER in page.locator('footer').inner_text()
        checks['theme_toggle_persists'] = True

        # Employee answer -> cited chunk -> standalone source page whose back link returns to /ask.
        page.locator('#persona option[value=employee]').wait_for(state='attached')
        page.locator('#persona').select_option('employee')
        page.get_by_text('employee · demo-a', exact=True).wait_for()
        page.locator('#ask-form button[type=submit]').click()
        page.locator('#result .answer-head').wait_for()
        cited = page.locator('#result .citation a').first.get_attribute('href')
        query = dict(part.split('=', 1) for part in cited.split('?', 1)[1].split('&'))
        page.goto(f"{origin}/sources/{query['version']}/{query['chunk']}")
        assert page.locator('.source-text').inner_text().strip()
        assert page.locator('a.back-link').get_attribute('href') == '/ask'
        checks['source_back_link_to_ask'] = True

        # Policy timeline marks exactly one version in effect today.
        page.goto(origin + '/policies?document=sg-travel')
        page.locator('#history-form button').click()
        page.locator('#result .version-head').first.wait_for()
        assert page.locator('#result .version-current').count() == 1
        checks['policy_timeline_one_current'] = True

        # Phone width: no horizontal page scroll on the main views.
        page.set_viewport_size({'width': 375, 'height': 812})
        for path in ('/cases', '/ask', '/policies', '/sources', '/audit'):
            page.goto(origin + path)
            overflow = page.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth')
            assert overflow <= 0, (path, overflow)
        checks['no_horizontal_scroll_375px'] = True

        assert not errors, errors
        print(json.dumps({'result': 'pass', 'checks': checks,
                          'external_requests': 'blocked by browser routing',
                          'full_browser_e2e': False, 'page_errors': errors}, indent=2))
        browser.close()
finally:
    server.should_exit = True
    thread.join(timeout=5)
