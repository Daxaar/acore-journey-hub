"""Crafting analysis and dashboard-owned decisions: acore#1 / phases #3–#6."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

from crafting import CraftingCatalogue, ReviewConflict, differences, fingerprint
from crafting_assessments import apply_panel
from prepare_crafting_assets import sql_rows, availability, dominates, stats, complex_item


def record(entry=2568):
    baseline={'entry':entry,'name':'Brown Linen Vest','RequiredLevel':3,'armor':15,'stat_type1':0,'stat_value1':0}
    r={'id':entry,'name':baseline['name'],'baseline':baseline,'proposed':dict(baseline),'slot':5,'quality':1,'type':'cloth',
       'assessment':'manual review','scope':'initial','reasoning':[],'limitations':[],
       'recipes':[{'id':2385,'name':'Brown Linen Vest','profession':197,'required_skill':10}],
       'availability':{'low':5,'high':15,'confidence':'medium'}}
    r['fingerprint']=fingerprint(r)
    return r


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'assets').mkdir()
        self.r=record();self.write([self.r]);self.store=CraftingCatalogue(self.root)

    def write(self,records):
        (self.root/'assets/crafting-catalogue.json').write_text(json.dumps({'format':1,'provenance':{'test':True},'records':records}))

    def payload(self,**changes):
        return {'id':2568,'status':'approved','notes':'Scenario checked','revision':0,'fingerprint':self.r['fingerprint'],**changes}

    def test_empty_install_needs_no_groups_game_database_or_sqlite(self):
        (self.root/'assets/crafting-catalogue.json').unlink()
        result=self.store.get({})
        self.assertFalse(result['available']);self.assertEqual(result['items'],[])
        self.assertFalse(self.store.path.exists())

    def test_read_details_does_not_create_review_database(self):
        self.assertEqual(self.store.get({'id':['2568']})['history'],[])
        self.assertFalse(self.store.path.exists())

    def test_filters_and_injection_inputs(self):
        self.assertEqual(self.store.get({'profession':['197'],'min':['1'],'max':['10'],'type':['cloth']})['total'],1)
        self.assertEqual(self.store.get({'q':['not there']})['total'],0)
        for params in [{'x':['1']},{'q':['a','b']},{'min':['61']},{'min':['10'],'max':['1']},{'profession':['197 OR 1=1']},{'review':['DROP TABLE']},{'id':['2568'],'q':['x']}]:
            with self.subTest(params=params),self.assertRaises(ValueError):self.store.get(params)

    def test_decision_survives_restart_and_has_history(self):
        self.store.save(self.payload())
        fresh=CraftingCatalogue(self.root)
        result=fresh.get({'id':['2568']})
        self.assertEqual(result['item']['review']['status'],'approved')
        self.assertEqual(result['history'][0]['revision'],1)
        fresh.save(self.payload(status='deferred',revision=1))
        self.assertEqual(len(fresh.get({'id':['2568']})['history']),2)

    def test_stale_revision_cannot_overwrite_other_window(self):
        self.store.save(self.payload())
        with self.assertRaises(ReviewConflict):self.store.save(self.payload(status='rejected'))
        self.assertEqual(self.store.get({'id':['2568']})['item']['review']['status'],'approved')

    def test_two_store_concurrent_saves_have_one_winner(self):
        self.store.save(self.payload())
        results=[]
        def save():
            try:CraftingCatalogue(self.root).save(self.payload(revision=1));results.append('saved')
            except ReviewConflict:results.append('conflict')
        threads=[threading.Thread(target=save) for _ in range(2)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertCountEqual(results,['saved','conflict'])

    def test_regeneration_retains_decision_but_marks_evidence_stale(self):
        self.store.save(self.payload())
        r=copy.deepcopy(self.r);r['proposed']['armor']=18;r['fingerprint']=fingerprint(r);self.write([r])
        result=self.store.get({'id':['2568']})['item']
        self.assertTrue(result['review']['stale']);self.assertEqual(result['review']['status'],'approved')
        with self.assertRaises(ReviewConflict):self.store.save(self.payload(revision=1))
        self.assertEqual(self.store.get({'review':['stale']})['total'],1)

    def test_baseline_and_proposal_remain_independent(self):
        r=record();apply_panel(r)
        self.assertEqual(r['baseline']['armor'],15);self.assertEqual(r['proposed']['armor'],18)
        self.assertEqual(differences(r['baseline'],r['proposed'])['armor']['difference'],3)
        r['baseline']['armor']=16
        with self.assertRaises(ValueError):apply_panel(r)

    def test_tooltips_use_original_stats_for_list_detail_and_comparators(self):
        r=record();apply_panel(r);r['comparators']=[{'id':999,'baseline':{**r['baseline'],'entry':999,'name':'Alternative','armor':21}}]
        self.write([r])
        self.assertEqual(self.store.get({})['items'][0]['tooltip']['armor'],15)
        item=self.store.get({'id':['2568']})['item']
        self.assertEqual(item['tooltip']['armor'],15)
        self.assertEqual(item['proposed']['armor'],18)
        self.assertEqual(item['comparators'][0]['tooltip']['armor'],21)

    def test_invalid_review_never_writes(self):
        for changes in [{'revision':True},{'status':'deployed'},{'notes':'x'*5001},{'id':99999},{'notes':None}]:
            with self.subTest(changes=changes),self.assertRaises((ValueError,LookupError)):self.store.save(self.payload(**changes))
        self.assertFalse(self.store.path.exists())


class MethodTests(unittest.TestCase):
    def test_mysql_dump_parser_handles_quotes_commas_and_escaped_strings(self):
        rows=list(sql_rows("INSERT INTO `item_template` VALUES (1,2,'a,(3,4), b'),(5,6,'O\\'Brien');"))
        self.assertEqual(rows,[['1','2','a,(3,4), b'],['5','6',"O'Brien"]])

    def test_acquisition_never_collapses_to_equip_requirement(self):
        recipes=[{'required_skill':240,'sources':[{'kind':'trainer','level':0}], 'recipe_items':[], 'specialization':False,'skill_conflict':False}]
        r=availability({'RequiredLevel':18},recipes)
        self.assertEqual((r['low'],r['high']),(35,60))
        self.assertIsNone(r['scenarios'][1]['high'])

    def test_uncertain_recipe_expands_band_and_lowers_confidence(self):
        r=availability({'RequiredLevel':10},[{'required_skill':75,'sources':[],'recipe_items':[],'specialization':False,'skill_conflict':False}])
        self.assertEqual(r['high'],60);self.assertEqual(r['confidence'],'low')

    def test_pareto_does_not_turn_stat_tradeoff_into_total_score(self):
        self.assertFalse(dominates({'stat:3':10},{'stat:7':1}))
        self.assertTrue(dominates({'stat:3':2,'armor':15},{'stat:3':1,'armor':15}))
        self.assertFalse(dominates({'armor':15},{'armor':15}))


class HttpTests(unittest.TestCase):
    setUp=CatalogueTests.setUp
    write=CatalogueTests.write
    payload=CatalogueTests.payload
    def test_http_token_origin_validation_and_conflict(self):
        from dashboard import handler
        class Cache:
            bots=[]
            class groups:data={'selected':None,'groups':[]}
            class notes:
                @staticmethod
                def get():return {}
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(Cache(),0,crafting=self.store))
        # Handler's Host guard needs the allocated port.
        server.RequestHandlerClass=handler(Cache(),server.server_port,crafting=self.store)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        with urlopen(base+'/api/session') as response:token=json.load(response)['token']
        def post(headers):return urlopen(Request(base+'/api/crafting/review',data=json.dumps(self.payload()).encode(),headers={'Content-Type':'application/json',**headers}))
        for headers in [{},{'X-Dashboard-Token':token,'Origin':'https://evil.example'}]:
            with self.assertRaises(HTTPError) as exc:post(headers)
            self.assertEqual(exc.exception.code,403)
        with post({'X-Dashboard-Token':token}) as response:self.assertTrue(json.load(response)['ok'])
        with self.assertRaises(HTTPError) as exc:post({'X-Dashboard-Token':token})
        self.assertEqual(exc.exception.code,409)


if __name__=='__main__':unittest.main()
