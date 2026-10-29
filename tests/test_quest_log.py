"""Saved journal ownership, complete history, bounded world search and reward semantics."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from quest_log import QuestLogProvider, query_sql, read_quests, base_xp, quest_faction, ALLIANCE_RACES, HORDE_RACES
from mysql_access import DatabaseError
from dashboard import objectives


def quest(**values):
    return {'kind':'quest','id':413,'title':'Shimmer Stout','level':10,'category_id':1,
            'template_found':1,'status':1,'LogDescription':'Take the barrel.','QuestDescription':'Hello $N.$BStory.',
            'RewardXPDifficulty':3,**values}


class QuestLogTests(unittest.TestCase):
    def provider(self, rows):
        provider=QuestLogProvider(objectives,reader=lambda sql:rows)
        provider.metadata={'areas':{'1':'Dun Morogh'},'spells':{'133':'Fireball'},'xp':{'10':[0,85,210,420]}}
        return provider

    def test_party_status_orders_members_and_distinguishes_current_and_history(self):
        rows=[{'kind':'party_status','name':name,'level':10,'class':1,'status':status,'rewarded':rewarded}
              for name,status,rewarded in [('Aster',1,0),('Bran',3,1),('Cora',5,0),('Dena',0,1),('Eryn',None,0)]]
        group={'id':'band','name':'The Band','members':['Eryn','Dena','Cora','Bran','Aster','Fenn']}
        result=self.provider(rows).party_status(group,413)
        self.assertEqual([c['state'] for c in result['characters']],['missing','completed','failed','active','ready','not_found'])
        self.assertTrue(result['characters'][3]['previously_completed'])
        self.assertEqual(result['group']['name'],'The Band')
        self.assertEqual(self.provider([]).party_status(None,413)['characters'],[])

    def test_party_query_is_bounded_read_only_and_includes_reset_history(self):
        calls=[]
        p=QuestLogProvider(objectives,reader=lambda sql:calls.append(sql) or [])
        group={'id':'one','name':'One','members':['Aster']}
        p.party_status(group,413);sql=calls[0]
        for clause in ['CONSISTENT SNAPSHOT, READ ONLY','MAX_EXECUTION_TIME=3000','LIMIT 6','s.quest=413','r.quest=413','0x4173746572']:
            self.assertIn(clause,sql)
        self.assertNotIn('r.active=',sql)
        for value in [0,-1,'413',True,2147483648]:
            with self.assertRaises(ValueError):p.party_status(group,value)
        with self.assertRaises(ValueError):p.party_status({**group,'members':['Aster;DROP']},413)
        self.assertEqual(len(calls),1)

    def test_party_class_restrictions_do_not_replace_recorded_progress(self):
        group={'id':'band','name':'The Band','members':['Aster','Bran','Cora','Dena','Eryn','Fenn']}
        rows=[{'kind':'restriction','title':'Muren Stormpike','class_mask':1}]
        rows += [{'kind':'party_status','name':name,'class':cid,'status':status,'rewarded':rewarded}
                 for name,cid,status,rewarded in [('Aster',1,None,0),('Bran',8,None,0),('Cora',4,3,0),
                                                ('Dena',2,None,1),('Eryn',5,1,0),('Fenn',3,5,0)]]
        result=self.provider(rows).party_status(group,1679)
        self.assertEqual(result['allowed_classes'],['Warrior'])
        self.assertEqual(result['title'],'Muren Stormpike')
        self.assertEqual([c['state'] for c in result['characters']],
                         ['missing','ineligible_class','active','completed','ready','failed'])
        rows[0]['class_mask']=1|128
        self.assertEqual(self.provider(rows).party_status(group,1679)['allowed_classes'],['Warrior','Mage'])
        rows[0]['class_mask']=0
        self.assertEqual(self.provider(rows).party_status(group,1679)['characters'][1]['state'],'missing')

    def test_class_filter_applies_to_count_results_details_and_cache(self):
        for mode in ['active','completed','all']:
            sql=query_sql(mode,name='Aster',search='light',page=1,class_id=2)
            # Both count and page queries must exclude unrestricted and other-class quests.
            self.assertEqual(sql.count('class_filter.AllowableClasses=2'),2)
            self.assertNotIn('COALESCE(class_filter.AllowableClasses,0)<=0',sql)
            self.assertIn('LIMIT 50 OFFSET 50',sql)
            detail=query_sql(mode,name='Aster',quest_id=413,class_id=2)
            self.assertIn('class_filter.AllowableClasses=2',detail)
        self.assertNotIn('class_filter',query_sql('all'))
        self.assertIn('class_filter.AllowableClasses=1024',query_sql('all',class_id=11))
        for value in [-1,10,12,'2',True,None]:
            with self.subTest(value=value),self.assertRaises(ValueError):query_sql('all',class_id=value)
        calls=[]
        p=QuestLogProvider(objectives,reader=lambda sql:calls.append(sql) or [{'kind':'count','total':0}])
        p.get('all',class_id=1);p.get('all',class_id=2);p.get('all',class_id=2)
        self.assertEqual(len(calls),2)

    def test_playerbot_watch_status_supports_all_32_without_expanding_saved_groups(self):
        names=['Bot'+chr(65+i//26)+chr(65+i%26) for i in range(32)]
        group={'id':'playerbot-watch','name':'Playerbot Watch','members':names}
        calls=[]
        p=QuestLogProvider(objectives,reader=lambda sql:calls.append(sql) or [])
        result=p.party_status(group,413,watch=True)
        self.assertEqual([c['name'] for c in result['characters']],names)
        self.assertIn('LIMIT 32',calls[0])
        with self.assertRaises(ValueError):p.party_status(group,413)
        with self.assertRaises(ValueError):p.party_status({**group,'members':names+['Extra']},413,watch=True)
        self.assertEqual(p.party_status({**group,'members':[]},413,watch=True)['characters'],[])
        self.assertEqual(len(calls),1)

    def test_faction_badges_require_unambiguous_direct_or_mandatory_race_restrictions(self):
        self.assertEqual(quest_faction(ALLIANCE_RACES),'alliance')
        self.assertEqual(quest_faction(HORDE_RACES),'horde')
        self.assertEqual(quest_faction(512),'horde')
        self.assertEqual(quest_faction(1024),'alliance')
        self.assertEqual(quest_faction(0,[0,512,None]),'horde')
        self.assertEqual(quest_faction(ALLIANCE_RACES|HORDE_RACES,[64]),'alliance')
        for mask in [None,0,-1,0xffffffff,ALLIANCE_RACES|HORDE_RACES,1|2,1<<25]:
            with self.subTest(mask=mask):self.assertIsNone(quest_faction(mask))
        self.assertIsNone(quest_faction(1,[2]))
        result=self.provider([quest(race_mask=0,prerequisite_race_masks=[512])]).get('all')
        self.assertEqual(result['quests'][0]['quest_side'],'horde')
        self.assertNotIn('prerequisite_race_masks',result['quests'][0])

    def test_faction_crest_does_not_overwrite_reputation_objective_faction(self):
        provider=self.provider([quest(race_mask=512,faction=911,reputation_required=3000)])
        provider.metadata['factions']={'911':'Silvermoon City'}
        q=provider.get('all',quest_id=413)['quests'][0]
        self.assertEqual(q['quest_side'],'horde')
        self.assertEqual(q['faction'],911)
        self.assertEqual(q['objectives'][0]['label'],'Reputation with Silvermoon City')

    def test_obsolete_title_filter_applies_before_pagination_and_exact_id_lookup(self):
        predicate="UPPER(COALESCE(q.LogTitle,'')) NOT REGEXP '<[[:space:]]*(UNUSED|DEPRECATED)[[:space:]]*>'"
        for mode in ['active','completed','all']:
            sql=query_sql(mode,name='Aster',page=2)
            self.assertEqual(sql.count(predicate),2)
            self.assertIn('LIMIT 50 OFFSET 100',sql)
            self.assertIn(predicate,query_sql(mode,name='Aster',quest_id=413))
            self.assertIn("'race_mask',q.AllowableRaces",sql)
            self.assertIn('fr0.PrevQuestID>0 AND fr1.ExclusiveGroup=0',sql)

    def test_character_and_world_views_require_different_ownership(self):
        for mode in ['active','completed']:
            with self.assertRaises(LookupError): self.provider([quest()]).get(mode,'Aster',quest_id=413)
        world=self.provider([quest()]).get('all',quest_id=413)
        self.assertIsNone(world['character'])
        self.assertEqual(world['quests'][0]['state'],'catalogue')
        with self.assertRaises(LookupError): self.provider([{'kind':'character','name':'Aster','level':9}]).get('active','Aster',quest_id=999)

    def test_completed_has_no_invented_objective_counters_and_active_status_is_authoritative(self):
        rows=[{'kind':'character','name':'Aster','level':9},quest(target1=10,target_count1=3,mob1=3,status=3)]
        active=self.provider(rows).get('active','Aster',quest_id=413)['quests'][0]
        self.assertEqual(active['state'],'active')
        self.assertEqual(active['objectives'][0]['current'],3)
        completed=self.provider(rows).get('completed','Aster',quest_id=413)['quests'][0]
        self.assertEqual(completed['state'],'completed')
        self.assertIsNone(completed['objectives'][0]['current'])
        self.assertEqual(completed['base_xp'],420)

    def test_no_completed_history_is_restricted_to_party_comparisons_or_active_flags(self):
        sql=query_sql('completed','Aster')
        self.assertIn('character_queststatus_rewarded',sql)
        self.assertNotIn('s.active=1',sql)
        self.assertNotIn('s2.quest',sql)
        self.assertIn('COUNT(*)',sql)
        self.assertIn('LIMIT 50 OFFSET 0',sql)

    def test_world_search_does_not_join_characters_and_hex_encodes_text(self):
        sql=query_sql('all',search="Stout'; DROP TABLE x; --",page=2)
        self.assertNotIn('acore_characters',sql)
        self.assertNotIn("Stout';",sql)
        self.assertIn('0x'+"Stout'; DROP TABLE x; --".encode().hex(),sql)
        self.assertIn('LOWER(CONVERT(',sql)
        self.assertIn('LIMIT 50 OFFSET 100',sql)
        self.assertIn('q.ID=413',query_sql('all',search='413'))
        for clause in ['MAX_EXECUTION_TIME=3000','CONSISTENT SNAPSHOT, READ ONLY','COMMIT;']:
            self.assertIn(clause,sql)

    def test_invalid_parameters_are_rejected_before_reader(self):
        with patch('quest_log.read_quests') as read:
            for params in [dict(mode='bad'),dict(name='../Aster'),dict(name='Aster',page=-1),dict(mode='all',page=10001),
                           dict(mode='all',quest_id=0),dict(mode='all',quest_id='1;DROP'),dict(mode='all',search='x'*101),dict(mode='all',search='a\nb')]:
                with self.subTest(params=params),self.assertRaises(ValueError): query_sql(**params)
            read.assert_not_called()

    def test_unknown_templates_and_empty_histories(self):
        rows=[{'kind':'character','name':'Aster','level':9},quest(title=None,template_found=0)]
        value=self.provider(rows).get('completed','Aster',quest_id=413)['quests'][0]
        self.assertEqual(value['title'],'Quest #413')
        self.assertEqual(value['objectives'],[])
        self.assertIsNone(value['base_xp'])
        empty=self.provider(rows[:1]+[{'kind':'count','total':0}]).get('completed','Aster')
        self.assertEqual(empty['total'],0)
        self.assertEqual(empty['quests'],[])

    def test_rewards_keep_choice_items_distinct_and_use_named_lookup(self):
        rows=[quest(fixed_id1=1,fixed_name1='One',fixed_count1=2,choice_id1=2,choice_name1='Two',choice_count1=1,RewardSpell=133)]
        q=self.provider(rows).get('all',quest_id=413)['quests'][0]
        self.assertEqual([r['kind'] for r in q['rewards']],['fixed','choice'])
        self.assertEqual(q['reward_spells'][0]['name'],'Fireball')
        self.assertEqual(q['category'],'Dun Morogh')

    def test_reward_tooltip_details_merge_without_changing_reward_kind_or_count(self):
        rows=[quest(fixed_id1=1,fixed_name1='One',fixed_count1=2,choice_id1=1,choice_name1='One',choice_count1=1),
              {'kind':'reward_item','id':1,'level':20,'armor':25,'stat_type1':7,'stat_value1':3,'sell_price':200}]
        rewards=self.provider(rows).get('all',quest_id=413)['quests'][0]['rewards']
        self.assertEqual([(r['kind'],r['count']) for r in rewards],[('fixed',2),('choice',1)])
        for reward in rewards:
            self.assertEqual(reward['armor'],25)
            self.assertEqual(reward['stat_value1'],3)
            self.assertEqual(reward['sell_price'],200)
        sql=query_sql('all',quest_id=413)
        self.assertIn("'kind','reward_item'",sql)
        self.assertIn("'stat_value10',t.stat_value10",sql)
        self.assertIn('LIMIT 10;',sql)

    def test_base_xp_rounding_scaling_and_missing_metadata(self):
        meta={'xp':{'10':[0,85,210,420], '20':[0,500]}}
        self.assertEqual(base_xp(10,9,3,meta),420)
        self.assertEqual(base_xp(10,30,3,meta),40)
        self.assertEqual(base_xp(-1,20,1,meta),500)
        self.assertIsNone(base_xp(99,1,3,meta))

    def test_transport_confirms_readonly_and_hides_cli_errors(self):
        for output in ['','{}','{"kind":"meta","read_only":0}']:
            with patch('quest_log.subprocess.run',return_value=subprocess.CompletedProcess([],0,output,'')):
                with self.assertRaises(DatabaseError):read_quests('SELECT 1')
        with patch('quest_log.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','secret')):
            with self.assertRaisesRegex(DatabaseError,'Cannot read saved quest data'):read_quests('SELECT 1')

    def test_cache_does_not_substitute_other_character_or_view(self):
        calls=[]
        def reader(sql):
            calls.append(sql)
            return [{'kind':'character','name':'Aster','level':9},quest()]
        p=QuestLogProvider(objectives,reader=reader)
        p.get('active','Aster');p.get('active','Aster')
        self.assertEqual(len(calls),1)
        p.get('completed','Aster');p.get('all')
        self.assertEqual(len(calls),3)


class QuestLogHttpTests(unittest.TestCase):
    def test_quest_routes_validate_parameters_and_serve_only_explicit_assets(self):
        import threading
        from http.server import ThreadingHTTPServer
        from urllib.request import urlopen
        from urllib.error import HTTPError
        import dashboard
        rows=[{'kind':'character','name':'Aster','level':9},quest()]
        with patch('dashboard.QuestLogProvider',lambda builder:QuestLogProvider(builder,reader=lambda sql:rows)):
            server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.handler(fixture_cache(reader=lambda names:[]),0))
            server.RequestHandlerClass=dashboard.handler(fixture_cache(reader=lambda names:[]),server.server_port)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            result=json.load(urlopen(base+'/api/quest?mode=active&name=Aster&id=413'))
            self.assertEqual(result['result']['quests'][0]['state'],'ready')
            self.assertTrue(json.load(urlopen(base+'/api/quests?mode=all'))['ok'])
            self.assertTrue(json.load(urlopen(base+'/api/quests?mode=all&q=light&class=2'))['ok'])
            self.assertTrue(json.load(urlopen(base+'/api/quest?mode=all&id=413&class=2'))['ok'])
            watch=json.load(urlopen(base+'/api/quest-party?id=413&roster=watch'))['result']
            self.assertEqual(watch['group']['name'],'Playerbot Watch')
            self.assertEqual([c['name'] for c in watch['characters']],['Galen'])
            party=json.load(urlopen(base+'/api/quest-party?id=413'))['result']
            self.assertEqual(party['group']['id'],'band')
            self.assertEqual(len(party['characters']),6)
            for path in ['/api/quest?mode=all&id=0','/api/quests?mode=all&page=-1',
                         '/api/quest-party?id=0','/api/quest-party?id=413&id=414','/api/quest-party?id=413&names=Aster',
                         '/api/quests?mode=all&mode=active','/api/quests?mode=active&name=../Aster',
                         '/api/quests?mode=all&arbitrary=1','/api/quests?mode=all&class=10',
                         '/api/quests?mode=all&class=2&class=1','/api/quest-party?id=413&roster=bad']:
                with self.subTest(path=path),self.assertRaises(HTTPError) as error:urlopen(base+path)
                self.assertEqual(error.exception.code,400)
            for path in ['/quest-log','/quest-log.js','/quest-log.css','/quest-horde.svg','/quest-alliance.svg']:
                self.assertEqual(urlopen(base+path).status,200)
            with self.assertRaises(HTTPError) as error:urlopen(base+'/quest_log.py')
            self.assertEqual(error.exception.code,404)
        finally:
            server.shutdown();server.server_close();thread.join()


from test_support import fixture_cache

if __name__=='__main__':unittest.main()
