"""Evidence-based eligibility, priorities and map-separated candidate routes."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard import SnapshotCache, build_view
from planning import missing_reason, enrich_view, nearest, LocationProvider, location_sql
from test_dashboard import character, quest
from mysql_access import DatabaseError, snapshot_sql
from activity_history import ActivityHistory

META={'areas':{'1':'Dun Morogh','38':'Loch Modan','1537':'Ironforge'},'world_areas':{'341':{'map':0,'area':1537}}}


def saved(name,guid,**kwargs):
    return {**character(name,guid),'eligibility_data_complete':1,'reward_history_complete':1,'map':0,'x':0,'y':0,**kwargs}


def definition(guid=1,**kwargs):
    return {**quest(guid),'min_level':8,'category_id':1,**kwargs}


def missing(rows,q=None):
    c=build_view(rows,['Bran'])['characters'][0]
    return missing_reason(c,q or definition(),rows)


class EligibilityTests(unittest.TestCase):
    def test_level_race_class_and_skill_are_confirmed_saved_blockers(self):
        rows=[saved('Bran',2)]
        q=definition(min_level=12,race_mask=1,class_mask=2,required_skill=171,required_skill_points=20)
        result=missing(rows,q)
        self.assertEqual(result['confidence'],'blocked')
        self.assertTrue(any('level 12' in reason for reason in result['reasons']))
        self.assertTrue(any('race' in reason for reason in result['reasons']))
        self.assertTrue(any('class' in reason for reason in result['reasons']))
        self.assertTrue(any('skill #171' in reason for reason in result['reasons']))
        rows.append({'kind':'skill','guid':2,'id':171,'value':30})
        self.assertFalse(any('skill #171' in reason for reason in missing(rows,q)['reasons']))

    def test_passed_checks_are_never_called_eligible_or_not_accepted(self):
        result=missing([saved('Bran',2)])
        self.assertEqual(result['confidence'],'unknown')
        self.assertIn('unverified',result['label'])
        self.assertTrue(any('Scripts' in reason for reason in result['reasons']))
        self.assertEqual(missing([character('Bran',2)])['confidence'],'unknown')

    def test_completed_and_reset_history_are_distinct(self):
        rows=[saved('Bran',2),{'kind':'rewarded','guid':2,'quest':287,'active':1}]
        self.assertEqual(missing(rows)['confidence'],'recorded')
        rows[-1]['active']=0
        result=missing(rows)
        self.assertEqual(result['confidence'],'unknown')
        self.assertTrue(any('inactive/reset' in r for r in result['reasons']))
        view=build_view([*rows,definition()],['Bran'])
        self.assertEqual(view['quests'],[])  # other character's quest does not appear in a solo comparison

    def test_prerequisite_alternatives_are_or_not_all_required(self):
        deps=[{'kind':'dependency','quest':287,'id':10,'signed_id':10,'title':'First','group':0},
              {'kind':'dependency','quest':287,'id':11,'signed_id':11,'title':'Alternative','group':0}]
        rows=[saved('Bran',2),*deps]
        self.assertEqual(missing(rows)['confidence'],'blocked')
        rows.append({'kind':'rewarded','guid':2,'quest':11,'active':1})
        self.assertEqual(missing(rows)['confidence'],'unknown')
        deps[0]['group']=-3
        self.assertTrue(any('Grouped' in r for r in missing(rows)['reasons']))

    def test_negative_prerequisite_can_be_active_or_nonrepeatably_rewarded(self):
        dep={'kind':'dependency','quest':287,'id':10,'signed_id':-10,'title':'Run','group':0}
        rows=[saved('Bran',2),dep]
        self.assertEqual(missing(rows)['confidence'],'blocked')
        rows.append(definition(2,id=10))
        self.assertEqual(missing(rows)['confidence'],'unknown')
        rows.pop();rows.append({'kind':'rewarded','guid':2,'quest':10,'active':1})
        self.assertEqual(missing(rows)['confidence'],'unknown')
        for flags in [1,16]:
            dep['special_flags']=flags
            self.assertTrue(any('Grouped' in r for r in missing(rows)['reasons']))

    def test_live_unavailable_and_missing_template_do_not_create_blockers(self):
        self.assertEqual(missing([saved('Bran',2,quest_state_available=False)])['confidence'],'unknown')
        self.assertEqual(missing([saved('Bran',2)],definition(template_found=0))['confidence'],'unknown')


class PlanTests(unittest.TestCase):
    def test_only_saved_ready_characters_get_handin_actions(self):
        rows=[saved('Aster',1),saved('Bran',2),definition(status=3,mob1=5,explored=0),definition(2,status=1)]
        view=enrich_view(build_view(rows,['Aster','Bran']),rows,{'locations':{}},META)
        actions=view['planning']['actions']
        handin=next(a for a in actions if a['kind']=='handin')
        self.assertEqual(handin['characters'],['Bran'])
        self.assertEqual(actions[0]['kind'],'handin')
        self.assertTrue(any(a['kind']=='catchup' and a['characters']==['Aster'] for a in actions))

    def test_same_zone_is_not_proof_of_objective_location_and_race_is_not_a_side_quest_rule(self):
        rows=[saved('Aster',1),saved('Bran',2,race=4),definition(),definition(2)]
        view=enrich_view(build_view(rows,['Aster','Bran']),rows,{'locations':{}},META)
        self.assertTrue(any(a['kind']=='shared' for a in view['planning']['actions']))
        self.assertFalse(any(a['kind']=='side' for a in view['planning']['actions']))
        self.assertTrue(view['planning']['unknown_locations'])
        self.assertTrue(all(not route for route in view['planning']['routes'].values()))

    def test_alternative_handins_choose_one_and_maps_do_not_share_coordinates(self):
        rows=[saved('Aster',1),definition(status=1)]
        locs=[{'kind':'location','quest':287,'role':'handin','source':'Possible saved spawn','map':mapid,
               'zone':1,'x':x,'y':0,'name':name,'objective':None} for mapid,x,name in [(0,9000,'Far'),(0,20,'Near'),(1,0,'Other map')]]
        view=enrich_view(build_view(rows,['Aster']),rows,{'locations':{287:locs}},META)
        route=view['planning']['routes']['1']
        self.assertEqual(len(route),1)
        self.assertEqual(route[0]['activities'][0]['name'],'Near')
        self.assertTrue(route[0]['activities'][0]['alternative'])
        order=nearest([{'map':1,'zone':'A','priority':0,'x':0,'y':0},{'map':0,'zone':'B','priority':0,'x':900,'y':0}],{'map':0,'x':0,'y':0})
        self.assertEqual([s['map'] for s in order],[0,1])

    def test_distinct_objectives_are_kept_but_finished_objective_areas_are_not_routed(self):
        rows=[saved('Aster',1),definition(target2=2,target_count2=3,mob2=0,mob1=5,explored=1,special_flags=0)]
        locs=[{'kind':'location','quest':287,'role':'objective','source':'Quest map area','map':0,
               'zone':1,'x':i*2000,'y':0,'name':'Search area','objective':i} for i in (0,1)]
        view=enrich_view(build_view(rows,['Aster']),rows,{'locations':{287:locs}},META)
        route=view['planning']['routes']['1']
        self.assertEqual(len(route),1)
        self.assertEqual(route[0]['x'],2000)

    def test_quest_map_region_preferred_to_broad_saved_spawn_zone(self):
        rows=[saved('Aster',1),definition(status=1)]
        locs=[{'kind':'location','quest':287,'role':'handin','source':'Possible saved spawn','map':0,'zone':1,'x':0,'y':0,'name':'NPC','objective':None},
              {'kind':'location','quest':287,'role':'handin','source':'Quest map area','map':0,'world_area':341,'zone':0,'x':1,'y':1,'name':'Marker','objective':-1}]
        view=enrich_view(build_view(rows,['Aster']),rows,{'locations':{287:locs}},META)
        self.assertEqual(view['planning']['routes']['1'][0]['zone'],'Ironforge')

    def test_geo_failure_does_not_prevent_priorities(self):
        provider=LocationProvider(lambda sql:(_ for _ in ()).throw(DatabaseError('test failure')))
        geo=provider.get([287]);self.assertIsNotNone(geo['warning'])
        rows=[saved('Aster',1),definition(status=1)]
        view=enrich_view(build_view(rows,['Aster']),rows,geo,META)
        self.assertEqual(view['planning']['actions'][0]['kind'],'handin')
        self.assertIsNotNone(view['planning']['warning'])
        for invalid in [[],['287'],[0],[1]*1001]:
            with self.assertRaises(ValueError):location_sql(invalid)

    def test_query_reads_complete_bounded_history_and_reverse_prerequisites(self):
        sql=snapshot_sql(['Aster'])
        for clause in ['reward_history_complete','eligibility_data_complete','LIMIT 20001',"'kind','dependency'",'a.NextQuestID','character_skills']:
            self.assertIn(clause,sql)
        self.assertNotIn('r.active=1',sql)


if __name__=='__main__':unittest.main()
