"""Gear score explanations, lawful transfers, equipment combinations and read-only boundaries."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from gear_planner import (PlannerPreferences,GearPlanner,effective,equip_checks,compare_candidate,transferable,
                         adventure_plans,source_state,weights,effort_points)
from gear_sources import snapshot_sql,read_snapshot,read_items
from mysql_access import DatabaseError


def item(**values):
    return {'entry':1,'name':'A test item','class':4,'subclass':1,'InventoryType':5,'Quality':2,'ItemLevel':10,
      'RequiredLevel':1,'AllowableClass':-1,'AllowableRace':-1,'armor':10,'block':0,'stat_type1':7,'stat_value1':2,**values}


def character(**values):
    return {'guid':7,'account':8,'name':'Aster','class':1,'race':1,'level':10,'role':'tank','money':10000,
      'skills':{415:1,43:50,433:1},'spells':set(),'guilds':{1},'quests':{},'rewarded':set(),'equipped':{},**values}


def owned(**values):return {'kind':'owned','label':'Aster · bags','owner':7,'owner_name':'Aster','activity':'own:7','activity_name':'Use owned gear',**values}


def instance(**values):return {'guid':100,'owner':7,'account':8,'flags':0,'random':0,'enchants':'',**values}


class GearPlannerTests(unittest.TestCase):
    def test_preferences_are_empty_atomic_persistent_and_validate_roles(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'gear-planner.json';prefs=PlannerPreferences(path)
            self.assertEqual(prefs.get(),{});self.assertFalse(path.exists())
            prefs.save(7,'healer');self.assertEqual(PlannerPreferences(path).get(),{'7':'healer'})
            for guid,role in [(True,'tank'),(0,'tank'),(7,'unknown')]:
                with self.assertRaises(ValueError):prefs.save(guid,role)
            prefs.save(7,'');self.assertEqual(prefs.get(),{})

    def test_empty_group_never_reads_database_or_seeds_roles(self):
        reader=Mock(side_effect=AssertionError('No database read'))
        result=GearPlanner(root=Path('/tmp/nonexistent-gear-fixture'),reader=reader).get(None)
        self.assertEqual(result['characters'],[]);self.assertEqual(result['activities'],[]);reader.assert_not_called()

    def test_score_uses_stats_not_item_level_and_requires_an_explicit_role(self):
        low=item(ItemLevel=1,stat_value1=5);high=item(ItemLevel=200,stat_value1=5)
        a=compare_candidate(low,instance(),character(),owned(),{},5)
        b=compare_candidate(high,instance(),character(),owned(),{},5)
        self.assertEqual(a['gain'],b['gain'])
        self.assertAlmostEqual(a['gain'],sum(a['contributions'].values()),places=2)
        self.assertIsNone(compare_candidate(low,instance(),character(role=''),owned(),{},5))
        self.assertGreater(weights('healer',2)['intellect'],weights('tank',2).get('intellect',0))

    def test_transfer_rules_respect_soulbound_bop_account_binding_and_raid_trade_flags(self):
        target=character()
        self.assertTrue(transferable(instance(flags=1),item(bonding=1),target))
        self.assertFalse(transferable(instance(owner=9,flags=1|256),item(),target))
        self.assertFalse(transferable(instance(owner=9),item(bonding=1),target))
        self.assertTrue(transferable(instance(owner=9),item(bonding=2),target))
        self.assertTrue(transferable(instance(owner=9,flags=1),item(Flags=0x08000000),target))
        self.assertFalse(transferable(instance(owner=9,account=99,flags=1),item(Flags=0x08000000),target))

    def test_proficiencies_race_class_and_requirements_are_checked(self):
        self.assertIsNone(equip_checks(item(AllowableClass=2),character()))
        self.assertIsNone(equip_checks(item(AllowableClass=0),character()))
        self.assertIsNone(equip_checks(item(FlagsExtra=1),character()))
        self.assertIsNone(equip_checks(item(AllowableRace=2),character()))
        self.assertIsNone(equip_checks(item(subclass=4),character()))
        self.assertIsNone(equip_checks(item(InventoryType=28,subclass=7),character()))
        checks=equip_checks(item(RequiredSkill=202,RequiredSkillRank=100),character())
        self.assertTrue(checks['notes'])
        rec=compare_candidate(item(RequiredLevel=12),instance(),character(),owned(),{},5)
        self.assertEqual(rec['availability'],'soon')
        self.assertIsNone(compare_candidate(item(RequiredLevel=16),instance(),character(),owned(),{},5))

    def test_two_handed_comparison_includes_lost_offhand_and_cannot_duplicate_one_instance(self):
        main=item(entry=2,**{'class':2},subclass=7,InventoryType=13,stat_value1=5)
        off=item(entry=3,InventoryType=14,stat_value1=8)
        equipped={15:{'template':main,'instance':instance(guid=200),'stats':{'stamina':5},'notes':[]},16:{'template':off,'instance':instance(guid=201),'stats':{'stamina':8},'notes':[]}}
        twohand=item(entry=4,**{'class':2},subclass=7,InventoryType=17,stat_value1=10,armor=0)
        self.assertIsNone(compare_candidate(twohand,instance(),character(equipped=equipped),owned(),{},0))
        strong={**twohand,'stat_value1':20};rec=compare_candidate(strong,instance(),character(equipped=equipped),owned(),{},0)
        self.assertEqual(rec['replace_slots'],[15,16]);self.assertEqual(rec['delta']['stamina'],7)
        # A single item cannot remain in the main hand and also fill the off hand.
        duplicate=compare_candidate(main,instance(guid=200),character(equipped=equipped,spells={674}),owned(),{},0)
        self.assertIsNone(duplicate)

    def test_unique_rings_cannot_duplicate_other_kept_ring(self):
        ring=item(InventoryType=11,maxcount=1,stat_value1=10)
        current={'template':ring,'instance':instance(guid=200),'stats':{'stamina':10,'armor':10},'notes':[]}
        self.assertIsNone(compare_candidate(ring,instance(),character(equipped={10:current}),owned(),{},0))

    def test_unresolved_effects_are_provisional_and_known_enchants_are_counted(self):
        values,notes=effective(item(),instance(enchants='99 0 0'),{})
        self.assertIn('Unresolved enchantment #99',notes)
        meta={'enchants':{'99':{'types':[5,0,0],'args':[7,0,0],'amount':[3,0,0]}}}
        values,notes=effective(item(),instance(enchants='99 0 0'),meta)
        self.assertEqual(values['stamina'],5);self.assertEqual(notes,[])
        rec=compare_candidate(item(spellid_1=12,spelltrigger_1=0),instance(),character(),owned(),{},0)
        self.assertEqual(rec['confidence'],'review')

    def test_passive_stats_and_random_properties_are_not_double_counted(self):
        meta={'properties':{'12':[99]},'enchants':{'99':{'types':[5,0,0],'args':[7,0,0],'amount':[3,0,0]}},
          'spells':{'100':{'effects':[6,0,0],'auras':[29,0,0],'base':[3,0,0],'die':[1,0,0],'misc':[0,0,0],'scale':[0,0,0]}}}
        values,notes=effective(item(spellid_1=100,spelltrigger_1=1),instance(random=12),meta)
        self.assertEqual(values['stamina'],5);self.assertEqual(values['strength'],4)
        raw='0 0 0 '*7+'99 0 0'
        values,_=effective(item(),instance(random=12,enchants=raw),meta)
        self.assertEqual(values['stamina'],5)

    def test_quest_completion_and_race_restrictions_exclude_rewards(self):
        q={'ID':12,'SpecialFlags':0,'Flags':0,'AllowableRaces':0,'AllowableClasses':0,'prev_race':0,'prev_class':0,'MaxLevel':0,
          'PrevQuestID':0,'RequiredSkillID':0,'RequiredSkillPoints':0,'ExclusiveGroup':0,'conditions':0,'QuestLevel':10}
        source={'kind':'quest','quest':q}
        self.assertIsNone(source_state(source,character(rewarded={12}),item()))
        self.assertEqual(source_state(source,character(),item())[0],'check')
        self.assertEqual(source_state(source,character(quests={12:1}),item())[0],'now')
        self.assertEqual(source_state({**source,'quest':{**q,'QuestLevel':40}},character(),item())[0],'later')
        self.assertIsNone(source_state({**source,'quest':{**q,'AllowableClasses':2}},character(),item()))

    def test_cross_faction_owned_items_are_excluded_and_guild_withdrawals_checked(self):
        source=owned(owner=9,owner_name='Briar',owner_race=2)
        self.assertIsNone(source_state(source,character(),item()))
        self.assertIsNone(compare_candidate(item(),instance(owner=9),character(),source,{},0))
        self.assertIsNone(compare_candidate(item(Flags=0x08000000),instance(owner=9,flags=1),character(),source,{},0))
        self.assertEqual(source_state({**source,'owner_race':3},character(),item())[0],'now')
        self.assertEqual(source_state(source,character(race=2),item())[0],'now')
        self.assertIsNone(source_state({**source,'owner_race':1},character(race=2),item()))
        self.assertEqual(source_state({'kind':'vendor','extended':0,'cost':10,'faction':35},character(),item(RequiredLevel=12),{'player_factions':{'1':1},'faction_templates':{'1':{'faction':1,'group':3},'35':{'faction':35,'hostile':0}}})[0],'soon')
        guild={'kind':'guild','guild':2,'label':'A guild','activity':'g:2','activity_name':'Bank'}
        rec=compare_candidate(item(),instance(owner=9),character(),guild,{},0)
        self.assertEqual(rec['availability'],'check');self.assertTrue(any('withdraw' in n for n in rec['notes']))

    def test_group_plan_never_counts_one_shared_instance_twice_or_multiple_choice_rewards(self):
        a=compare_candidate(item(),instance(),character(),owned(),{},0)
        b={**a,'gain':10}
        chars=[{'name':'Aster','recommendations':[a,b]},{'name':'Briar','recommendations':[a]}]
        plans=adventure_plans(chars)
        self.assertEqual(plans[0]['members'],1)
        self.assertEqual(plans[0]['beneficiaries'][0]['item_details']['armor'],10)
        self.assertEqual(plans[0]['beneficiaries'][0]['item_details']['stat_value1'],2)
        quests={**a,'resource':None,'source':{**a['source'],'kind':'quest','activity':'q:1'}}
        plans=adventure_plans([{'name':'Aster','recommendations':[quests,quests]}])
        self.assertEqual(plans[0]['members'],1)

    def test_sql_scope_is_read_only_bounded_and_names_are_hex_encoded(self):
        sql=snapshot_sql(['Aster'],['Briar'])
        for text in ['CONSISTENT SNAPSHOT, READ ONLY','LIMIT 12001','LIMIT 20001','character_inventory','guild_bank_item','c.account IN','0x4173746572','0x4272696172']:
            self.assertIn(text,sql)
        self.assertNotIn('acore_auth',sql)
        with self.assertRaises(ValueError):snapshot_sql(['x;DROP'],[])
        with self.assertRaises(DatabaseError):read_snapshot(['Aster'],reader=lambda sql:[{'kind':'owner'}]*501)

    def test_effort_estimates_distinguish_ready_quests_recipes_and_expensive_token_vendors(self):
        self.assertLess(effort_points({'kind':'quest','id':12},character(quests={12:1})),effort_points({'kind':'quest','id':12},character()))
        self.assertLess(effort_points({'kind':'craft','learned':True,'materials_ready':True},character()),effort_points({'kind':'craft','learned':False,'materials_ready':False},character()))
        self.assertLess(effort_points({'kind':'vendor','cost':1,'extended':0},character()),effort_points({'kind':'vendor','cost':100000,'extended':1},character()))

    def test_item_queries_are_batched_and_template_mapping_is_explicit(self):
        reader=Mock(return_value=[]);self.assertEqual(read_items(range(1,1002),reader),{})
        self.assertEqual(reader.call_count,3)
        self.assertTrue(all('READ ONLY' in call.args[0] for call in reader.call_args_list))

    def test_role_cannot_be_saved_for_a_character_outside_the_selected_group(self):
        prefs=PlannerPreferences();p=GearPlanner(reader=lambda sql:[],preferences=prefs)
        with self.assertRaises(ValueError):p.set_role({'members':['Aster']},12,'tank')
        self.assertEqual(prefs.get(),{})

    def test_full_snapshot_prioritises_owned_upgrade_over_larger_quest_reward(self):
        from gear_sources import ITEM_FIELDS,Q_FIELDS,QA_FIELDS
        base=item(entry=1,stat_value1=1);bag=item(entry=2,stat_value1=10);reward=item(entry=3,stat_value1=100)
        templates={i['entry']:i for i in [base,bag,reward]}
        q={key:0 for key in [*Q_FIELDS,*QA_FIELDS]};q.update(ID=12,LogTitle='A bigger reward',MinLevel=1,QuestLevel=10)
        rows=[{'kind':'character','guid':7,'account':8,'name':'Aster','class':1,'race':1,'level':10,'money':1000},
          {'kind':'owner','guid':7,'account':8,'name':'Aster'},
          {'kind':'inventory',**instance(guid=100),'entry':1,'owner_name':'Aster','bag':0,'slot':4,'location':'equipped'},
          {'kind':'inventory',**instance(guid=101),'entry':2,'owner_name':'Aster','bag':0,'slot':23,'location':'bags'},
          {'kind':'skill','guid':7,'id':415,'value':1}]
        def reader(sql):
            if "'kind','template'" in sql:return [{'kind':'template','v':[t.get(f,0) for f in ITEM_FIELDS]} for t in templates.values()]
            if any(kind in sql for kind in ["'kind','eligibility_condition'","'kind','eligibility_contact'","'kind','eligibility_item'"]):return []
            if "'kind','eligibility'" in sql:return [{'kind':'eligibility','id':12,'races':0,'classes':0,'prev':0,'next':0,'group':0,'auto':True}]
            if "'kind','qsource'" in sql:return [{'kind':'qsource','v':[q[f] for f in [*Q_FIELDS,*QA_FIELDS]]+[[3],0,0,0]}]
            if "'kind','vendor'" in sql:return []
            return rows
        prefs=PlannerPreferences();prefs.roles={'7':'tank'}
        planner=GearPlanner(root=Path('/tmp/nonexistent-gear-fixture'),reader=reader,preferences=prefs)
        result=planner.get({'id':'band','name':'Band','members':['Aster']})
        recs=result['characters'][0]['recommendations']
        self.assertEqual(recs[0]['item']['id'],2);self.assertEqual(recs[0]['source']['kind'],'owned')
        self.assertGreater(next(r for r in recs if r['source']['kind']=='quest')['gain'],recs[0]['gain'])
        self.assertEqual(result['activities'][0]['kind'],'owned')
        self.assertEqual(planner.get({'id':'band','name':'Band','members':['Aster']})['characters'][0]['role'],'tank')


class GearPlannerHttpTests(unittest.TestCase):
    def test_empty_setup_assets_parameter_validation_and_role_authentication(self):
        import json
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.request import Request,urlopen
        from urllib.error import HTTPError
        import dashboard
        reader=Mock(side_effect=AssertionError('Empty group must not read game data'))
        planner=GearPlanner(root=Path('/tmp/nonexistent-gear-fixture'),reader=reader)
        cache=dashboard.SnapshotCache(reader=lambda names:[])
        server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.handler(cache,0,planner=planner))
        server.RequestHandlerClass=dashboard.handler(cache,server.server_port,planner=planner)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/gear-planner') as response:self.assertEqual(json.load(response)['result']['characters'],[])
            for path in ['/gear-planner','/gear-planner.js','/gear-planner.css']:
                with urlopen(base+path) as response:self.assertEqual(response.status,200)
            for query in ['?threshold=1','?threshold=5&threshold=10','?names=Aster','?threshold=DROP']:
                with self.subTest(query=query),self.assertRaises(HTTPError) as error:urlopen(base+'/api/gear-planner'+query)
                self.assertEqual(error.exception.code,400)
            with urlopen(base+'/api/session') as response:token=json.load(response)['token']
            for auth,status in [('',403),(token,400)]:
                req=Request(base+'/api/gear-planner/role',data=b'{"guid":7,"role":"tank"}',headers={'Content-Type':'application/json','X-Dashboard-Token':auth})
                with self.assertRaises(HTTPError) as error:urlopen(req)
                self.assertEqual(error.exception.code,status)
            reader.assert_not_called()
        finally:server.shutdown();server.server_close();thread.join()
