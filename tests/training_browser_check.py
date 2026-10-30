"""Optional WSL-only Playwright check with synthetic trainer and character records."""
import copy
import json
import sys
import tempfile
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import dashboard
from journal import JournalStore
from training import TrainingProvider
from test_training import META,ROWS
from unittest.mock import patch


def main():
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);(root/'assets').mkdir()
        metadata=copy.deepcopy(META);metadata['spells']['555'].update(name='Frostbolt',description='Deals 10 Frost damage.',power_type=0,cost=30)
        (root/'assets/tooltip-metadata.json').write_text(json.dumps(metadata));calls=[]
        def reader(sql):
            calls.append(sql)
            if '0x4173746572' in sql:return ROWS
            if '0x4272616e' in sql:return [{'kind':'character','guid':2,'name':'Bran','race':1,'class':8,'level':4}]
            return []
        provider=TrainingProvider(root,reader)
        cache=dashboard.SnapshotCache(reader=lambda names:[],groups_file=root/'groups.json')
        cache.update_groups({'action':'create','name':'Example party','members':['Aster','Bran']})
        with patch('dashboard.TrainingProvider',return_value=provider):
            server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.handler(cache,0,journal=JournalStore(root/'journal.sqlite3')))
            server.RequestHandlerClass=dashboard.handler(cache,server.server_port,journal=JournalStore(root/'journal.sqlite3'))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1080});page.set_default_timeout(8000)
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                base=f'http://127.0.0.1:{server.server_port}'
                page.goto(base+'/training');page.locator('.training-ability').first.wait_for()
                assert page.locator('.training-ability').count()==4
                assert page.get_by_role('heading',name='Coming Soon',exact=True).is_visible()
                assert page.get_by_role('heading',name='Not Yet Available',exact=True).is_visible()
                nav=page.locator('.page-nav').inner_text();assert nav.index('Armory')<nav.index('Gear Planner')<nav.index('What’s Training')
                assert page.locator('.page-nav > *').last.inner_text()=='Settings'
                ability=page.locator('.training-ability').filter(has_text='Demoralizing Shout');ability.scroll_into_view_if_needed()
                page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))');ability.hover()
                tooltip=page.locator('#training-tooltip');tooltip.wait_for(state='visible')
                assert all(text in tooltip.inner_text() for text in ['Rank 1','15 Rage','Instant','Requires Level 14','Effect of Demoralizing Shout','Base training cost:'])
                assert tooltip.locator('a').count()==0
                image=tooltip.locator(':scope > .tooltip-icon').bounding_box();body=tooltip.locator(':scope > .tooltip-body').bounding_box()
                assert image['x']+image['width']<=body['x'] and abs(image['y']-body['y'])<1
                assert ability.evaluate('(e) => getComputedStyle(e).cursor')=='pointer'
                ability.focus();assert tooltip.is_visible();page.keyboard.press('Escape');assert tooltip.is_hidden()
                screenshot=ROOT/'docs/screenshots/training.png';screenshot.parent.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(screenshot),full_page=True)
                page.get_by_label('Ability name or ID',exact=True).fill('Heroic')
                page.wait_for_function("() => document.querySelectorAll('.training-ability').length===1")
                assert 'Level 16' in page.locator('.training-list').inner_text()
                page.get_by_role('button',name='Clear filters',exact=True).click()
                page.get_by_label('Required level',exact=True).fill('14')
                page.wait_for_function("() => document.querySelectorAll('.training-ability').length===2")
                assert 'Heroic Strike' not in page.locator('.training-list').inner_text()
                page.get_by_label('Required level',exact=True).fill('16–20')
                page.wait_for_function("() => document.querySelector('.training-list').textContent.includes('Heroic Strike')")
                assert page.locator('.training-ability').count()==2
                passive=page.locator('.training-ability').filter(has_text='Dual Wield');passive.focus();tooltip.wait_for(state='visible')
                assert 'Passive' in tooltip.inner_text() and 'Instant' not in tooltip.inner_text()
                page.get_by_label('Required level',exact=True).fill('20-14')
                page.locator('#training-error').wait_for(state='visible');assert 'ascending' in page.locator('#training-error').inner_text()
                page.get_by_role('button',name='Clear filters',exact=True).click()
                page.get_by_label('Show',exact=True).select_option('unlearned')
                page.locator('.training-ability').filter(has_text='Skill gated').wait_for()
                page.get_by_label('Show',exact=True).select_option('all')
                page.get_by_role('heading',name='Already Learned',exact=True).wait_for()
                page.get_by_role('button',name='Bran',exact=True).click()
                page.locator('.training-ability').filter(has_text='Frostbolt').wait_for()
                assert 'Mage' in page.locator('#training-owner').inner_text()
                assert 'Heroic Strike' not in page.locator('#training-list').inner_text()
                page.get_by_role('button',name='Aster',exact=True).click()
                page.get_by_role('button',name='Clear filters',exact=True).click()
                page.locator('.training-ability').filter(has_text='Revenge').wait_for()
                page.set_viewport_size({'width':390,'height':844})
                ability=page.locator('.training-ability').filter(has_text='Revenge');ability.focus();tooltip.wait_for(state='visible')
                bounds=tooltip.bounding_box();assert bounds['x']>=0 and bounds['x']+bounds['width']<=390
                image=tooltip.locator(':scope > .tooltip-icon').bounding_box();assert image['x']>=0
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.get_by_label('Character',exact=True).fill('Missing');page.get_by_role('button',name='Open spellbook',exact=True).click()
                page.locator('#training-error').wait_for(state='visible');assert 'No saved character' in page.locator('#training-error').inner_text()
                # New installations do not select characters or contact the game database.
                empty=dashboard.SnapshotCache(reader=lambda names:[])
                with patch('dashboard.TrainingProvider',return_value=provider):server.RequestHandlerClass=dashboard.handler(empty,server.server_port,journal=JournalStore())
                previous=len(calls);page.goto(base+'/training');page.locator('#training-empty').wait_for(state='visible')
                assert not page.locator('.training-ability').count() and len(calls)==previous
                assert not errors,errors
                browser.close()
            print('PASS: real training API/UI, level/name filters, learned/passive/class states, hover/focus tooltips, mobile layout, missing characters and empty startup.')
        finally:server.shutdown();server.server_close()


if __name__=='__main__':main()
