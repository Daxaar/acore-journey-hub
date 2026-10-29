"""Real catalogue browser QA with temporary review storage; acore#1 / #6."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import dashboard
from crafting import CraftingCatalogue
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def main():
    output=ROOT/'.qa/crafting-work';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);(root/'assets').mkdir()
        (root/'assets/crafting-catalogue.json').symlink_to(ROOT/'assets/crafting-catalogue.json')
        store=CraftingCatalogue(root)
        cache=dashboard.SnapshotCache()
        server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.handler(cache,0,crafting=store))
        server.RequestHandlerClass=dashboard.handler(cache,server.server_port,crafting=store)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        errors=[];external=[]
        try:
            with sync_playwright() as pw:
                env={**os.environ,'LD_LIBRARY_PATH':str(ROOT/'.qa/sysroot/usr/lib/x86_64-linux-gnu'),
                     'XDG_CACHE_HOME':str(ROOT/'.qa/cache'),'XDG_CONFIG_HOME':str(ROOT/'.qa/config')}
                browser=pw.chromium.launch(env=env)
                context=browser.new_context(viewport={'width':1600,'height':1100})
                page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:external.append(r.url) if not r.url.startswith(base) else None)
                page.goto(base+'/crafting');page.wait_for_selector('#craft-rows tr')
                assert page.locator('#craft-rows tr').count()==40
                assert '692' in page.locator('#craft-count').inner_text()
                nav=page.locator('.page-nav').inner_text();assert nav.index('Armory & bags')<nav.index('Gear Planner')<nav.index('Quest log')
                assert page.locator('.page-nav > *').last.inner_text()=='Settings'
                page.get_by_label('Item name or ID').fill('Brown Linen Vest');page.get_by_role('button',name='Search ledger').click()
                page.wait_for_function("() => document.querySelectorAll('#craft-rows tr').length===1")
                crafted=page.get_by_role('button',name='Brown Linen Vest',exact=True)
                crafted.hover();page.locator('#craft-item-tooltip').wait_for(state='visible')
                assert '15 Armor' in page.locator('#craft-item-tooltip').inner_text()
                assert page.locator('#craft-item-tooltip a').count()==0
                crafted.focus();page.keyboard.press('Escape')
                assert page.locator('#craft-item-tooltip').is_hidden()
                page.get_by_role('button',name='Brown Linen Vest',exact=True).click()
                page.wait_for_selector('#craft-notes')
                assert '15 → 18 (+3)' in page.locator('#craft-detail').inner_text()
                assert page.locator('#craft-detail h2 a').get_attribute('href')=='https://www.wowhead.com/wotlk/item=2568'
                assert 'not reviewed'==page.locator('#craft-decision').input_value()
                alternative=page.locator('#craft-detail details > summary a').first
                alternative.scroll_into_view_if_needed()
                page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
                alternative.hover();page.locator('#craft-item-tooltip').wait_for(state='visible')
                assert alternative.inner_text() in page.locator('#craft-item-tooltip').inner_text()
                assert page.locator('#craft-item-tooltip a').count()==0
                page.mouse.move(0,0)
                other=context.new_page();other.goto(base+'/crafting?id=2568');other.wait_for_selector('#craft-notes')
                page.locator('#craft-decision').select_option('deferred');page.locator('#craft-notes').fill('Browser fixture only <script>alert(1)</script>')
                page.get_by_role('button',name='Save review',exact=True).click();page.wait_for_function("() => document.querySelector('#craft-save-status').textContent.includes('Review saved')")
                other.locator('#craft-decision').select_option('approved');other.get_by_role('button',name='Save review',exact=True).click()
                other.wait_for_function("() => document.querySelector('#craft-save-status').textContent.includes('another window')")
                other.close();page.reload();page.wait_for_selector('#craft-notes')
                assert page.locator('#craft-decision').input_value()=='deferred'
                assert '<script>' in page.locator('#craft-notes').input_value()
                page.locator('select[name=review]').select_option('deferred');page.get_by_role('button',name='Search ledger').click()
                page.wait_for_function("() => document.querySelector('#craft-count').textContent.includes('1 of')")
                page.screenshot(path=str(output/'crafting-desktop.png'),full_page=True)
                page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(output/'crafting-mobile.png'),full_page=True)
                assert page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth')
                # Render the real empty-state UI, not just an empty provider response.
                empty=CraftingCatalogue(root/'empty')
                server.RequestHandlerClass=dashboard.handler(cache,server.server_port,crafting=empty)
                page.goto(base+'/crafting')
                page.locator('#craft-empty').wait_for(state='visible')
                assert page.locator('#craft-rows tr').count()==0
                assert not empty.path.exists()
                page.screenshot(path=str(output/'crafting-empty.png'),full_page=True)
                assert not errors,errors
                assert not external,external
                browser.close()
            # The same application must render a usable empty installation without groups or generated assets.
            empty=CraftingCatalogue(root/'empty')
            assert not empty.get({})['available']
            assert not empty.path.exists()
            result={'browser':'PASS','real_catalogue':692,'review_storage':'temporary only','javascript_errors':errors,'external_requests':external,'mobile_width':390}
            (output/'browser-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
        finally:
            server.shutdown();server.server_close()


if __name__=='__main__':main()
