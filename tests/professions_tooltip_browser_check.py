"""Optional Playwright regression: synthetic profession tooltips, no game connection."""
import json
import os
from pathlib import Path
import re
import sys
import threading
from urllib.parse import urlsplit,parse_qs
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from settings import DEFAULTS
from armory import build_inventory


def main():
    from playwright.sync_api import sync_playwright
    class Static(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'static'),**kwargs)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Static)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    skill={'id':773,'name':'Inscription','category':11,'value':50,'max':75,'training':{'rank':'Journeyman','cap':150,'required_skill':50,'required_level':10},'profession':True,'icon':None}
    character={'name':'Aster','found':True,'level':80,'skills':[skill]}
    def item(entry,name):return {'id':entry,'name':name,'icon':None,'quality':1,'level':40,'description':'Synthetic '+name+' description','sell_price':125,'class_names':['Shaman'],'glyph_type':'Major Glyph','max_stack':20,'required_level':15,'spell_effects':[{'label':'Use','text':'Permanently teaches you this glyph.'},{'label':'','text':'Increases Lightning Shield damage by 20%.'}]}
    ink={**item(1003,'Ethereal Ink'),'owned':0,'required':1}
    paper={**item(1004,'Resilient Parchment'),'owned':0,'required':1}
    def recipe(entry,name,outputs):return {'id':entry,'name':name,'rank':'','status':'unlearned','difficulty':'unlearned','cast_time_ms':3000,'required_skill':1,'restricted':False,'description':'Synthetic spell description','outputs':outputs,'reagents':[ink,paper],'tools':[],'tool_categories':['Virtuoso Inking Set'],'focus':'','icon':None,'group':'Other','has_materials':False,'material_count':0}
    recipes=[recipe(2001,'Glyph of Barkskin',[{**item(1001,'Glyph of Barkskin'),'minimum':1,'maximum':1}]),recipe(2002,'Glyph of Arcane Power',[{**item(1002,'Glyph of Arcane Power'),'minimum':1,'maximum':1}]),recipe(2003,'Synthetic enchantment',[])]
    payloads={'/api/session':{'token':'synthetic','groups':{'selected':'example','groups':[{'id':'example','name':'Example','members':['Aster']}]}},
              '/api/settings':{'ok':True,'settings':DEFAULTS},
              '/api/skills':{'ok':True,'result':{'characters':[character],'professions':[skill]}},
              '/api/professions':{'ok':True,'result':{'characters':[character],'recipes':recipes,'refreshed_at':'2026-10-29T12:00:00Z'}}}
    items={i['id']:i for i in [*recipes[0]['outputs'],*recipes[1]['outputs'],ink,paper]}
    sword={**item(1005,'Example sword'),'class_names':[],'glyph_type':None,'MaxDurability':100,'armor':30,'spell_effects':[{'label':'Equip','text':'Increases attack power by 12.'}]}
    items[1005]=sword
    inventory=build_inventory([{'kind':'character','guid':7,'name':'Aster','race':7,'class':1,'level':80},
                               {'kind':'item','guid':1,'entry':1005,'owner':7,'bag':0,'slot':15,'name':'Example sword of Testing','Quality':3,'ItemLevel':40,'RequiredLevel':30,'MaxDurability':100,'durability':75,'count':1,'enchantments':'1 0 0','armor':35}],{'enchants':{'1':'+7 Agility'}})
    inventory['refreshed_at']='2026-10-29T12:00:00Z'
    payloads.update({'/api/armory':{'ok':True,'inventory':inventory},'/api/armory/space':{'ok':True,'space':{'characters':[]}},'/api/model':{'available':False}})
    delayed=[];lookups=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            page=browser.new_page(viewport={'width':1400,'height':1000});errors=[]
            page.set_default_timeout(5000)
            page.on('pageerror',lambda e:errors.append(str(e)))
            def api(route):
                url=urlsplit(route.request.url)
                if url.path=='/api/item-tooltip':
                    entry=int(parse_qs(url.query)['id'][0]);lookups.append(entry)
                    if entry==1007:delayed.append(route);return
                    route.fulfill(status=200 if entry in items else 503,json={'ok':entry in items,'item':items.get(entry)})
                else:route.fulfill(json=payloads.get(url.path,{'ok':True}))
            page.route('**/api/**',api)
            page.route('**/icons/**',lambda route:route.fulfill(path=str(ROOT/'static/item-placeholder.svg'),content_type='image/svg+xml'))
            page.goto(f'http://127.0.0.1:{server.server_port}/professions.html')
            page.get_by_role('button',name='Unlearned',exact=True).click()
            assert page.locator('.profession-summary-card .profession-trainable').count()==1
            bar=page.locator('.profession-summary-card .profession-trainable')
            assert bar.evaluate('(e)=>getComputedStyle(e).borderTopColor')=='rgb(255, 150, 46)'
            badge=page.locator('#prof-characters .profession-training-badge')
            assert badge.count()==1
            button=page.locator('#prof-characters button').first
            assert button.get_attribute('title') is None
            training_tip=page.locator('#profession-training-tooltip')
            button.hover();training_tip.wait_for(state='visible')
            assert all(text in training_tip.inner_text() for text in ['Aster','Inscription','Journeyman','cap 150','Requires skill 50','Level 10'])
            assert training_tip.locator('a').count()==0
            assert button.get_attribute('aria-describedby')=='profession-training-tooltip'
            page.keyboard.press('Escape');assert training_tip.is_hidden()
            button.focus();assert training_tip.is_visible()
            page.locator('#prof-refresh').focus();assert training_tip.is_hidden()
            page.set_viewport_size({'width':390,'height':844})
            button.focus();assert training_tip.is_visible()
            bounds=training_tip.bounding_box();assert bounds['x']>=0 and bounds['x']+bounds['width']<=390
            page.set_viewport_size({'width':1400,'height':1000})
            assert 'cap 150' in bar.get_attribute('title')
            tip=page.locator('#profession-item-tooltip')
            def check(target,name):
                target.scroll_into_view_if_needed();page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))');target.hover();tip.wait_for(state='visible')
                assert name in tip.inner_text() and 'Sell Price' in tip.inner_text()
                assert tip.locator('a').count()==0
                image=tip.locator(':scope > .tooltip-icon').bounding_box();body=tip.locator(':scope > .tooltip-body').bounding_box()
                assert image['x']+image['width']<=body['x'] and abs(image['y']-body['y'])<1
                assert target.evaluate('(e) => getComputedStyle(e).cursor')=='pointer'
                target.focus();assert tip.is_visible()
                page.keyboard.press('Escape');assert tip.is_hidden()
            check(page.locator('.recipe-row').filter(has_text='Glyph of Barkskin'),'Glyph of Barkskin')
            page.locator('.recipe-row').filter(has_text='Glyph of Arcane Power').click()
            check(page.locator('.recipe-detail-title'),'Glyph of Arcane Power')
            for name in ['Glyph of Arcane Power','Ethereal Ink','Resilient Parchment']:
                check(page.locator('.recipe-item').filter(has_text=name),name)
            link=page.locator('.recipe-item a').first
            assert link.get_attribute('href')=='https://www.wowhead.com/wotlk/item=1002'
            link.focus();assert tip.is_visible()
            page.evaluate('window.dispatchEvent(new Event("resize"))');assert tip.is_hidden()
            page.locator('#prof-refresh').focus();assert tip.is_hidden()
            enchant=page.locator('.recipe-row').filter(has_text='Synthetic enchantment');enchant.scroll_into_view_if_needed();page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))');enchant.hover();tip.wait_for(state='visible')
            assert 'Requires skill 1' in tip.inner_text() and 'Item level' not in tip.inner_text()
            page.get_by_label('Search recipes').fill('nothing matches');assert tip.is_hidden()
            page.set_viewport_size({'width':390,'height':844})
            page.get_by_label('Search recipes').fill('Glyph of Arcane Power')
            check(page.locator('.recipe-item').filter(has_text='Ethereal Ink'),'Ethereal Ink')
            page.set_viewport_size({'width':1400,'height':1000})
            page.get_by_label('Search recipes').fill('Glyph of Arcane Power')
            check(page.locator('.recipe-row').filter(has_text='Glyph of Arcane Power'),'Glyph of Arcane Power')
            page.locator('.recipe-row').filter(has_text='Glyph of Arcane Power').hover()
            assert all(t in tip.inner_text() for t in ['3 sec cast','Virtuoso Inking Set','Ethereal Ink','Major Glyph','Classes: Shaman','Max Stack: 20','20%'])
            # Exercise asynchronous enrichment, cache reuse, stale responses and outage fallback.
            page.evaluate('''() => { window.testTip=document.createElement('div');testTip.className='game-item-tooltip';document.body.append(testTip);testTip.hidden=false;ItemTooltip.render(testTip,{id:1007,name:'Old item'}); }''')
            page.wait_for_timeout(100)
            page.evaluate("ItemTooltip.render(testTip,{id:1005,name:'Example sword',armor:37})")
            page.wait_for_function("() => testTip.textContent.includes('attack power by 12')")
            assert '37 Armor' in page.evaluate('testTip.textContent')
            assert delayed
            delayed.pop().fulfill(json={'ok':True,'item':{'id':1007,'name':'Stale response'}})
            page.wait_for_timeout(100);assert 'Stale response' not in page.evaluate('testTip.textContent')
            page.evaluate("ItemTooltip.render(testTip,{id:1005,name:'Example sword',armor:37})")
            page.wait_for_timeout(100);assert lookups.count(1005)==1
            page.evaluate("ItemTooltip.render(testTip,{id:1006,name:'Fallback item',armor:42})")
            page.wait_for_function("() => testTip.textContent.includes('Additional server item details unavailable')")
            assert '42 Armor' in page.evaluate('testTip.textContent')
            # The detached icon and panel must both fit at every viewport corner.
            for width,height in [(1400,1000),(390,844)]:
                page.set_viewport_size({'width':width,'height':height})
                edges=page.evaluate('''() => {
                  const anchor=document.createElement('button');anchor.style.position='fixed';document.body.append(anchor);
                  testTip.hidden=false;ItemTooltip.render(testTip,{id:999,name:'Edge positioning',level:1,tooltip_complete:true});
                  const results=[];
                  for(const [x,y] of [[0,0],[innerWidth-1,0],[0,innerHeight-1],[innerWidth-1,innerHeight-1]]){
                    anchor.style.left=x+'px';anchor.style.top=y+'px';ItemTooltip.position(testTip,anchor,{clientX:x,clientY:y});
                    const icon=testTip.querySelector('.tooltip-icon').getBoundingClientRect(),body=testTip.querySelector('.tooltip-body').getBoundingClientRect();
                    results.push(icon.left>=0&&icon.top>=0&&icon.right<=body.left&&Math.abs(icon.top-body.top)<1&&body.right<=innerWidth&&body.bottom<=innerHeight);
                  }
                  anchor.remove();return results;
                }''')
                assert all(edges),edges
            page.set_viewport_size({'width':1400,'height':1000})
            # The actual armory now uses the shared renderer while preserving instance details.
            page.goto(f'http://127.0.0.1:{server.server_port}/armory.html?name=Aster')
            weapon=page.locator('[data-item-key="equipment:15"]');weapon.hover()
            armory_tip=page.locator('#item-tooltip');armory_tip.wait_for(state='visible')
            page.wait_for_function("() => document.querySelector('#item-tooltip').textContent.includes('attack power by 12')")
            assert all(t in armory_tip.inner_text() for t in ['Example sword of Testing','35 Armor','75 / 100','+7 Agility'])
            assert armory_tip.locator('a').count()==0
            image=armory_tip.locator(':scope > .tooltip-icon').bounding_box();body=armory_tip.locator(':scope > .tooltip-body').bounding_box()
            assert image['x']>=0 and image['x']+image['width']<=body['x']
            assert weapon.evaluate('(e) => getComputedStyle(e).cursor')=='pointer'
            assert not errors,errors
            browser.close()
        print('PASS: rich recipe/item tooltips, asynchronous enrichment/cache/race/outage handling, actual armory instance details, keyboard/mobile interactions; no browser errors.')
    finally:server.shutdown();server.server_close()


if __name__=='__main__':main()
