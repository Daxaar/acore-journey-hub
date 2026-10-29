"""Saved skills, automatic recipes, catalogue states and fixed read-only boundaries."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from professions import SkillsProvider,skills_sql,skill_records,recipe_records,difficulty
from mysql_access import DatabaseError
import dashboard


def ability(**values):return {'race':0,'class':0,'exclude_race':0,'exclude_class':0,'required':1,'acquire':0,'superseded':0,'gray':55,'yellow':15,**values}
def recipe(spell,**values):return {'id':spell,'name':'Recipe '+str(spell),'rank':'','description':'','base':[0,0,0],'icon':None,'outputs':[{'id':2862,'minimum':1,'maximum':1}],
 'reagents':[[2835,2]],'tools':[],'tool_categories':[],'focus':0,'abilities':[ability()],**values}
META={'skills':{'164':{'id':164,'name':'Blacksmithing','category':11,'description':'Smithing'},
                '182':{'id':182,'name':'Herbalism','category':11},'185':{'id':185,'name':'Cooking','category':9},
                '753':{'id':753,'name':'Racial - Gnome','category':9},'43':{'id':43,'name':'Swords','category':6}},
      'recipes':{'164':{'1':recipe(1),'2':recipe(2,abilities=[ability(acquire=2)]),'3':recipe(3,abilities=[ability(superseded=1)]),
                        '4':recipe(4,abilities=[ability(acquire=1,required=50)]),'5':recipe(5,abilities=[ability(race=1)])}},
      'items':{'2835':{'id':2835,'name':'Rough Stone','icon':None},'2862':{'id':2862,'name':'Stone','class':0,'subclass':8,'icon':None}}}
ROWS=[{'kind':'character','guid':1,'name':'Aster','race':7,'class':1,'level':10},
      {'kind':'skill','guid':1,'id':164,'value':40,'max':75},{'kind':'skill','guid':1,'id':753,'value':50,'max':50},
      {'kind':'skill','guid':1,'id':43,'value':30,'max':50},{'kind':'spell','guid':1,'id':1},
      {'kind':'material','id':2835,'count':5}]


class ProfessionTests(unittest.TestCase):
    def test_group_skill_order_missing_and_profession_classification(self):
        profiles=skill_records(ROWS,META,['Missing','Aster'])
        self.assertFalse(profiles[0]['found']);self.assertEqual(profiles[0]['skills'],[])
        skills={s['id']:s for s in profiles[1]['skills']}
        self.assertEqual((skills[164]['value'],skills[164]['max']),(40,75))
        self.assertTrue(skills[164]['profession']);self.assertFalse(skills[753]['profession'])
        self.assertEqual(skills[753]['group'],'Racial Skills');self.assertEqual(skills[43]['group'],'Weapon Skills')

    def test_learned_automatic_unlearned_and_superseded_are_distinct(self):
        c=skill_records(ROWS,META,['Aster'])[0];recipes={r['id']:r for r in recipe_records(ROWS,META,c,164)}
        self.assertEqual(recipes[1]['status'],'learned');self.assertEqual(recipes[1]['learning_source'],'Saved spellbook')
        self.assertEqual(recipes[2]['status'],'learned');self.assertEqual(recipes[2]['learning_source'],'Granted by saved skill')
        self.assertEqual(recipes[3]['status'],'superseded')
        self.assertEqual(recipes[4]['status'],'unlearned');self.assertTrue(recipes[5]['restricted'])
        self.assertEqual(recipes[1]['material_count'],2);self.assertEqual(recipes[1]['reagents'][0]['owned'],5)
        self.assertEqual(recipes[1]['difficulty'],'green')

    def test_untrained_profession_does_not_auto_grant_recipes(self):
        rows=[r for r in ROWS if r['kind']!='skill'];c=skill_records(rows,META,['Aster'])[0]
        recipes={r['id']:r for r in recipe_records(rows,META,c,164)}
        self.assertEqual(recipes[2]['status'],'unlearned')
        self.assertEqual(recipes[1]['status'],'learned') # explicit spell remains visible, even if no skill record

    def test_skill_value_acquisition_and_difficulty_boundaries(self):
        a=ability();self.assertEqual(difficulty(1,a,True),'orange');self.assertEqual(difficulty(15,a,True),'yellow')
        self.assertEqual(difficulty(35,a,True),'green');self.assertEqual(difficulty(55,a,True),'gray')
        self.assertEqual(difficulty(40,ability(required=50),True),'unavailable')
        self.assertEqual(difficulty(40,a,False),'unlearned')
        rows=[dict(r,value=50) if r['kind']=='skill' and r['id']==164 else r for r in ROWS]
        c=skill_records(rows,META,['Aster'])[0]
        self.assertEqual(next(r for r in recipe_records(rows,META,c,164) if r['id']==4)['status'],'learned')

    def test_missing_reagent_is_zero_and_material_count_is_not_a_craft_promise(self):
        rows=[r for r in ROWS if r['kind']!='material'];c=skill_records(rows,META,['Aster'])[0]
        r=recipe_records(rows,META,c,164)[0]
        self.assertEqual(r['reagents'][0]['owned'],0);self.assertFalse(r['has_materials']);self.assertEqual(r['material_count'],0)

    def test_duplicate_reagent_slots_are_added_before_material_checks(self):
        import copy
        metadata=copy.deepcopy(META)
        metadata['recipes']['164']['1']['reagents']=[[2835,2],[2835,4]]
        c=skill_records(ROWS,metadata,['Aster'])[0]
        r=next(r for r in recipe_records(ROWS,metadata,c,164) if r['id']==1)
        self.assertEqual(r['reagents'][0]['required'],6)
        self.assertFalse(r['has_materials']);self.assertEqual(r['material_count'],0)

    def test_fixed_readonly_sql_uses_carried_positions_not_bank(self):
        sql=skills_sql(['Aster'],True)
        for clause in ['CONSISTENT SNAPSHOT, READ ONLY','MAX_EXECUTION_TIME=3000','LIMIT 20001','LIMIT 2001',
                       'v.slot BETWEEN 23 AND 38','b.item=v.bag','b.slot BETWEEN 19 AND 22','SUM(i.count)','0x4173746572','COMMIT;']:
            self.assertIn(clause,sql)
        self.assertNotIn('guild_bank',sql)
        for names in [[],['Aster']*7,[None],["Aster';DROP"],'Aster']:
            with self.assertRaises(ValueError):skills_sql(names)
        with self.assertRaises(ValueError):skills_sql(['Aster','Bran'],True)

    def test_caps_fail_instead_of_displaying_partial_results(self):
        with self.assertRaises(DatabaseError):skill_records([{'kind':'spell','id':i} for i in range(20001)],META,['Aster'])
        with self.assertRaises(DatabaseError):skill_records([{'kind':'skill','id':i} for i in range(2001)],META,['Aster'])

    def test_provider_cache_scope_unknowns_and_catalogue_professions(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'assets').mkdir();(root/'assets'/'profession-metadata.json').write_text(json.dumps(META))
            calls=[]
            p=SkillsProvider(root,lambda sql:calls.append(sql) or ROWS)
            p.get(['Aster']);p.get(['Aster']);self.assertEqual(len(calls),1)
            data=p.get(['Aster'],164);self.assertEqual(len(calls),2)
            self.assertNotIn(753,[s['id'] for s in data['professions']])
            self.assertTrue(next(s for s in data['professions'] if s['id']==182)['gathering'])
            with self.assertRaises(ValueError):p.get(['Aster'],753)
            with self.assertRaises(LookupError):p.get(['Missing'],164)
            self.assertFalse(p.get(['Missing'])['characters'][0]['found'])
            with self.assertRaises(DatabaseError):SkillsProvider(Path(directory)/'missing').get(['Aster'])

    def test_http_routes_and_explicit_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'assets').mkdir();(root/'assets'/'profession-metadata.json').write_text(json.dumps(META))
            provider=SkillsProvider(root,lambda sql:ROWS)
            with patch('dashboard.SkillsProvider',lambda:provider):
                server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.handler(fixture_cache(reader=lambda names:[]),0))
                server.RequestHandlerClass=dashboard.handler(fixture_cache(reader=lambda names:[]),server.server_port)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
            try:
                self.assertTrue(json.load(urlopen(base+'/api/skills?names=Aster'))['ok'])
                self.assertTrue(json.load(urlopen(base+'/api/professions?name=Aster&skill=164'))['ok'])
                for path in ['/api/skills?names=Aster&names=Bran','/api/professions?name=Aster&skill=abc','/api/skills?name=Aster','/api/skills?names=../Aster']:
                    with self.assertRaises(HTTPError) as error:urlopen(base+path)
                    self.assertEqual(error.exception.code,400)
                for path in ['/professions','/professions.js','/professions.css','/skills-ui.js']:self.assertEqual(urlopen(base+path).status,200)
                with self.assertRaises(HTTPError) as error:urlopen(base+'/professions.py')
                self.assertEqual(error.exception.code,404)
            finally:server.shutdown();server.server_close();thread.join()


from test_support import fixture_cache

if __name__=='__main__':unittest.main()
