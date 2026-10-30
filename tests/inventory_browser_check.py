"""Optional Playwright regression for separate Armory/Inventory pages and shared tabs."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import dashboard
from armory import build_inventory
from journal import JournalStore


def main():
    from playwright.sync_api import sync_playwright, expect
    rows = [dict(kind='character', guid=7, name='Aster', level=20, race=1, **{'class':1}),
            dict(kind='guild', id=2, name='Explorers', money=100),
            dict(kind='guild_tab', id=0, name='Supplies'),
            dict(kind='item', guid=900, owner=7, bag=0, slot=23, entry=123, name='Travel bread', count=2, Quality=1)]
    snapshot = build_inventory(rows, {})
    snapshot['refreshed_at'] = '2026-10-30T16:00:00+00:00'
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        cache = dashboard.SnapshotCache(reader=lambda names: [], groups_file=root/'groups.json')
        store = JournalStore(root/'journal.sqlite3')
        with patch('dashboard.ArmoryProvider.get', return_value=snapshot):
            server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.handler(cache, 0, journal=store))
            server.RequestHandlerClass = dashboard.handler(cache, server.server_port, journal=store)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                for route in ['/crafting','/crafting.js','/api/crafting']:
                    try: urlopen(base+route)
                    except HTTPError as exc: assert exc.code == 404
                    else: raise AssertionError('Retired route still accessible: '+route)
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(args=['--no-sandbox'])
                    page = browser.new_page(viewport={'width':1440,'height':1080})
                    errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base+'/armory?name=Aster')
                    expect(page.locator('#character-title')).to_have_text('Aster')
                    assert page.locator('#bags').count() == 0
                    assert page.locator('.equipment-slot').count() == 19
                    page.locator('.page-nav a[href^="/inventory"]').click()
                    page.wait_for_selector('.bag-cell')
                    assert page.url.endswith('/inventory?name=Aster')
                    assert page.locator('#character-equipment-panel').count() == 0
                    page.locator('#bag-search').fill('bread')
                    assert '1 matching occupied slot' in page.locator('#bag-search-status').inner_text()
                    page.locator('.bag-cell').filter(has=page.locator('img')).first.click()
                    assert page.locator('#item-detail a').get_attribute('href').endswith('/item=123')
                    page.locator('#tab-bank').click(); assert 'Your bank' == page.locator('#bags-title').inner_text()
                    page.locator('#tab-bank').press('ArrowRight'); assert 'Explorers' in page.locator('#bags-title').inner_text()
                    for width in [1440,390]:
                        page.set_viewport_size({'width':width,'height':900})
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        assert page.locator('.page-nav [aria-current="page"]').inner_text() == 'Inventory'
                        labels = page.locator('.page-nav a').all_inner_texts()
                        assert labels[1:4] == ['Armory','Gear Planner','Inventory'] and labels[-1] == 'Settings'
                        page.locator('.page-nav a').first.focus()
                        assert page.locator('.page-nav a').first.evaluate('(e) => getComputedStyle(e).outlineStyle') != 'none'
                    page.locator('.page-nav a[href^="/armory"]').click()
                    expect(page.locator('#character-title')).to_have_text('Aster')
                    assert page.url.endswith('/armory?name=Aster')
                    page.goto(base+'/inventory'); expect(page.locator('#refresh-status')).to_contain_text('Enter a character')
                    assert page.locator('#inventory').is_hidden()
                    # Compare actual tab positions across every page at the same viewport.
                    routes = ['/', '/armory', '/gear-planner', '/inventory', '/quest-log', '/training', '/professions', '/auctions', '/journal', '/sql', '/settings']
                    for width in [1920,1440,1000,650,390]:
                        page.set_viewport_size({'width':width,'height':900})
                        baseline = None
                        for route in routes:
                            page.goto(base+route)
                            boxes = page.locator('.page-nav a').evaluate_all('(links) => links.map(e => { const r=e.getBoundingClientRect(); return [r.x,r.y,r.width,r.height].map(v=>Math.round(v*10)/10); })')
                            if baseline is None: baseline = boxes
                            assert boxes == baseline, (width,route,boxes,baseline)
                            assert page.locator('.page-nav').evaluate('(e) => e.getBoundingClientRect().right <= innerWidth'), (width,route)
                    page.goto(base+'/inventory?name=Aster')
                    expect(page.locator('#character-title')).to_have_text('Aster')
                    page.screenshot(path='/tmp/character-hub-consistent-tabs.png', full_page=True)
                    assert not errors, errors
                    browser.close()
            finally:
                server.shutdown(); server.server_close(); thread.join()
    print('Inventory, Armory, storage controls, empty state, responsive tabs and retired routes passed.')


if __name__ == '__main__': main()
