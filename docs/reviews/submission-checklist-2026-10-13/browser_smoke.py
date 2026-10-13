"""Isolated local browser check; creates only a disposable synthetic runtime."""
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

runtime = Path(tempfile.mkdtemp(prefix='seaglass-browser-', dir='/private/tmp'))
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
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1280, 'height': 900})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/')
                      else route.abort())
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin + '/')
        assert page.url == origin + '/cases'
        assert page.locator('[data-case]').count() == 7
        page.get_by_role('link', name='Travel-policy demo / choose persona').click()
        page.locator('#persona option[value=employee]').wait_for(state='attached')
        page.locator('#persona').select_option('employee')
        page.get_by_text('employee · demo-a', exact=True).wait_for()
        page.get_by_role('link', name='Case demo', exact=True).click()
        page.locator('[data-case=case_1] button').click()
        page.locator('[data-case=case_1] .answer-pre').wait_for()
        text = page.locator('[data-case=case_1] .case-result').inner_text()
        assert 'jira' in text and 'slack' in text and 'connection pool limit' in text
        page.screenshot(path=str(runtime / 'browser-home.png'), full_page=True)
        assert not errors, errors
        print(json.dumps({'result':'pass','scope':'home redirect, persona switch, fixed Jira/Slack case',
                          'external_requests':'blocked by browser routing',
                          'full_browser_e2e':False,'page_errors':errors}, indent=2))
        browser.close()
finally:
    server.should_exit = True
    thread.join(timeout=5)
