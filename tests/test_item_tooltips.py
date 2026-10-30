"""Spell resolution, bounded item lookups and the shared read-only HTTP endpoint."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
import dashboard
from item_tooltips import ItemTooltipProvider,item_sql
from mysql_access import DatabaseError
from spell_tooltips import spell_text,enrich_item,restrictions,CLASSES

DATA={'format':1,'spells':{'10':{'name':'Glyph','description':'Increases damage by $11s1%.','effects':[74,0,0],'misc':[2,0,0]},
                         '11':{'name':'Glyph effect','description':'Damage +$s1%.','base':[19,0,0],'die':[1,0,0]},
                         '12':{'name':'Periodic','description':'Lasts $d. Every $t1 sec.','duration':1,'period':[3000,0,0]}},
      'glyphs':{'2':{'spell':11,'flags':0}},'durations':{'1':15000}}
ITEM={'id':100,'name':'Glyph of Lightning Shield','AllowableClass':64,'AllowableRace':-1,'spellid_1':10,'spelltrigger_1':0,'max_stack':20,'sell_price':10000}


class SpellTextTests(unittest.TestCase):
    def test_cross_spell_values_and_base_point_offset(self):
        self.assertEqual(spell_text(10,DATA),('Increases damage by 20%.',True))
        self.assertEqual(spell_text(12,DATA),('Lasts 15 sec. Every 3 sec.',True))

    def test_missing_cycles_and_complex_expressions_are_not_guessed(self):
        data={'spells':{'1':{'description':'$999s1'},'2':{'description':'$@spelldesc2'},'3':{'description':'${$s1*2}'}}}
        for sid in (1,2,3,999):self.assertFalse(spell_text(sid,data)[1])
        self.assertNotIn('$',spell_text(3,data)[0])

    def test_dice_ranges_and_level_scaling_are_marked(self):
        data={'spells':{'1':{'description':'Deals $s1.','base':[4,0,0],'die':[3,0,0],'per_level':[1,0,0]}}}
        self.assertEqual(spell_text(1,data),('Deals 5–7.',False))

    def test_chain_radius_range_and_periodic_totals(self):
        data={'spells':{'1':{'description':'Affects $x1 targets within $a1 yards; range $r. Total $o1.',
                             'chain':[5,0,0],'radius':[2,0,0],'range':3,'duration':4,'base':[9,0,0],'die':[1,0,0],'period':[3000,0,0]}},
              'radii':{'2':8},'ranges':{'3':[30,30]},'durations':{'4':15000}}
        self.assertEqual(spell_text(1,data),('Affects 5 targets within 8 yards; range 30. Total 50.',True))

    def test_gem_stats_and_use_cooldowns_are_separate_from_glyph_text(self):
        data={**DATA,'gems':{'5':6},'enchants':{'6':'+16 Strength'}}
        gem=enrich_item({'gem_properties':5},data)
        self.assertEqual(gem['spell_effects'],[{'label':'','text':'+16 Strength'}])
        glyph=enrich_item({**ITEM,'spellcooldown_1':60000},data)
        self.assertEqual(glyph['spell_effects'][0]['cooldown_ms'],60000)
        self.assertNotIn('cooldown_ms',glyph['spell_effects'][1])

    def test_glyph_learning_effect_and_restrictions(self):
        item=enrich_item(ITEM,DATA)
        self.assertEqual(item['class_names'],['Shaman']);self.assertEqual(item['race_names'],[])
        self.assertEqual(item['glyph_type'],'Major Glyph')
        self.assertEqual(item['spell_effects'],[{'label':'Use','text':'Permanently teaches you this glyph.'},{'label':'','text':'Increases damage by 20%.'}])
        self.assertFalse(item['effects_incomplete']);self.assertNotIn('glyph_type',ITEM)
        self.assertEqual(restrictions(-1,CLASSES),[]);self.assertEqual(restrictions(1535,CLASSES),[])

    def test_unresolved_effect_is_explicit_and_missing_cast_is_not_instant(self):
        item=enrich_item({**ITEM,'spellid_1':999},DATA)
        self.assertTrue(item['effects_incomplete']);self.assertEqual(item['spell_effects'],[])

    def test_sets_socket_bonus_and_reputation_names(self):
        data={**DATA,'sets':{'3':{'name':'Example set','spells':[11],'counts':[2]}},'enchants':{'4':'+6 Stamina'},'factions':{'5':'Example faction'}}
        item=enrich_item({**ITEM,'itemset':3,'socketBonus':4,'required_faction':5},data)
        self.assertEqual(item['set_info']['bonuses'],[{'count':2,'text':'Damage +20%.'}])
        self.assertEqual(item['socket_bonus'],'+6 Stamina');self.assertEqual(item['faction_name'],'Example faction')


class ItemProviderTests(unittest.TestCase):
    def test_sql_is_bounded_read_only_and_invalid_ids_never_enter_sql(self):
        sql=item_sql(100)
        for clause in ['TRANSACTION READ ONLY','MAX_EXECUTION_TIME=3000','t.entry=100 LIMIT 1','COMMIT;','spellid_5','stackable','socketColor_3']:
            self.assertIn(clause,sql)
        for value in (0,-1,4294967296,True,'1;DROP TABLE x'):
            with self.assertRaises(ValueError):item_sql(value)

    def test_cache_normalization_and_missing_templates(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'assets').mkdir();(root/'assets/tooltip-metadata.json').write_text(json.dumps(DATA))
            calls=[];provider=ItemTooltipProvider(root,lambda sql:calls.append(sql) or [dict(ITEM)])
            item=provider.get(100);self.assertTrue(item['tooltip_complete']);self.assertEqual(item['glyph_type'],'Major Glyph')
            item['name']='changed';self.assertEqual(provider.get(100)['name'],ITEM['name']);self.assertEqual(len(calls),1)
            with self.assertRaises(LookupError):ItemTooltipProvider(root,lambda sql:[]).get(100)
            with self.assertRaises(DatabaseError):ItemTooltipProvider(root,lambda sql:[{'id':101}]).get(100)

    def test_http_validation_details_and_not_found(self):
        with tempfile.TemporaryDirectory() as folder:
            provider=ItemTooltipProvider(Path(folder),lambda sql:[dict(ITEM)] if 't.entry=100 ' in sql else [])
            with patch('dashboard.ItemTooltipProvider',return_value=provider):
                cache=dashboard.SnapshotCache(reader=lambda names:[])
                server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.handler(cache,0))
                server.RequestHandlerClass=dashboard.handler(cache,server.server_port)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            try:
                base=f'http://127.0.0.1:{server.server_port}'
                result=json.load(urlopen(base+'/api/item-tooltip?id=100'))
                self.assertTrue(result['ok']);self.assertEqual(result['item']['max_stack'],20)
                for query,code in [('id=0',400),('id=100&id=101',400),('id=100&extra=1',400),('id=999',404),('',400)]:
                    with self.assertRaises(HTTPError) as error:urlopen(base+'/api/item-tooltip?'+query)
                    self.assertEqual(error.exception.code,code)
            finally:server.shutdown();server.server_close()
