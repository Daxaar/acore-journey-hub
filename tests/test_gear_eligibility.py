"""Planner eligibility: class/race masks, hostile quest contacts and real prerequisite alternatives."""
import unittest
from gear_eligibility import QuestEligibility,npc_faction_access
from gear_planner import source_state
from test_gear_planner import character,item

META={'player_factions':{'1':1,'2':2},'faction_templates':{
 '1':{'faction':1,'group':3,'hostile':4},'2':{'faction':2,'group':5,'hostile':2},
 '35':{'faction':35,'group':0,'hostile':0},'68':{'faction':68,'group':4,'hostile':2},
 '12':{'faction':12,'group':2,'hostile':4}}}


def quest(qid,**values):
    return {'id':qid,'races':0,'classes':0,'prev':0,'next':0,'group':0,'auto':False,'starters':[35],**values}


def check(records,race=1,cls=8,conditions=(),**values):
    return QuestEligibility({q['id']:q for q in records},META,conditions).for_character({'race':race,'class':cls,'rewarded':set(),'quests':{},**values})


def condition(qid,kind,value,**values):
    return {'source':19,'quest':qid,'else_group':0,'type':kind,'value':value,'target':0,'negative':False,**values}


class GearEligibilityTests(unittest.TestCase):
    def test_vendor_sources_exclude_opposite_faction_and_unknown_but_keep_neutral(self):
        for race,allowed,blocked in [(1,12,68),(2,68,12)]:
            char=character(race=race)
            vendor={'kind':'vendor','npc':54,'name':'Vendor','cost':1,'extended':0,'faction':blocked}
            self.assertIsNone(source_state(vendor,char,item(),META))
            self.assertEqual(source_state({**vendor,'faction':allowed},char,item(),META)[0],'check')
            self.assertEqual(source_state({**vendor,'faction':35},char,item(),META)[0],'check')
            self.assertIsNone(source_state({**vendor,'faction':99999},char,item(),META))
            self.assertIsNone(source_state(vendor,char,item(),{}))
            self.assertIsNone(source_state({**vendor,'faction':None},char,item(),META))

    def test_vendor_faction_rules_honour_explicit_friend_and_enemy_lists(self):
        meta={**META,'faction_templates':{**META['faction_templates'],
          '88':{'faction':88,'group':4,'hostile':2,'friends':[1]},
          '89':{'faction':89,'group':0,'hostile':0,'enemies':[1]}}}
        self.assertTrue(npc_faction_access(meta,1,88))
        self.assertFalse(npc_faction_access(meta,1,89))
        self.assertIsNone(npc_faction_access(meta,999,35))

    def test_zero_race_mask_does_not_make_hostile_horde_giver_available_to_alliance(self):
        records=[quest(1,starters=[68]),quest(2,starters=[12]),quest(3)]
        alliance=check(records);horde=check(records,race=2)
        self.assertFalse(alliance(1));self.assertTrue(horde(1))
        self.assertTrue(alliance(2));self.assertFalse(horde(2))
        self.assertTrue(alliance(3));self.assertTrue(horde(3))

    def test_all_start_paths_and_turnin_contacts_are_considered(self):
        records=[quest(1,starters=[68,35]),quest(2,starters=[35],enders=[68]),
                 quest(3,starters=[],objects=[0]),quest(4,starters=[68],objects=[0]),
                 quest(5,starters=[35],enders=[68],end_objects=[0])]
        evaluate=check(records)
        self.assertTrue(evaluate(1));self.assertFalse(evaluate(2));self.assertTrue(evaluate(3));self.assertTrue(evaluate(4));self.assertTrue(evaluate(5))

    def test_class_and_race_masks_allow_general_and_multiclass_quests(self):
        records=[quest(1,classes=128),quest(2,classes=2),quest(3,races=2),quest(4,classes=128|2),quest(5)]
        mage=check(records);warrior=check(records,cls=1)
        self.assertTrue(mage(1));self.assertFalse(mage(2));self.assertFalse(mage(3));self.assertTrue(mage(4));self.assertTrue(mage(5))
        self.assertFalse(warrior(1));self.assertFalse(warrior(4));self.assertTrue(warrior(5))

    def test_restrictions_propagate_through_multiple_mandatory_prerequisites(self):
        records=[quest(1,starters=[68]),quest(2,prev=1),quest(3,prev=2),quest(4,classes=2),quest(5,prev=4)]
        evaluate=check(records)
        self.assertFalse(evaluate(3));self.assertFalse(evaluate(5))
        self.assertTrue(check(records,race=2)(3))

    def test_next_quest_links_create_alternative_not_intersected_paths(self):
        records=[quest(1,starters=[68],next=3),quest(2,starters=[12],next=3),quest(3,prev=1)]
        self.assertTrue(check(records)(3));self.assertTrue(check(records,race=2)(3))
        self.assertFalse(check([records[0],records[2]])(3))

    def test_each_from_all_negative_group_requires_every_eligible_predecessor(self):
        records=[quest(1,group=-1),quest(2,classes=2,group=-1),quest(3,prev=1)]
        self.assertFalse(check(records)(3))
        self.assertTrue(check(records,cls=2)(3))
        self.assertTrue(check(records,rewarded={1,2})(3))

    def test_completed_predecessor_is_proof_but_active_positive_parent_still_needs_possible_turnin(self):
        records=[quest(1,starters=[68],enders=[68]),quest(2,prev=1),quest(3,prev=-1)]
        self.assertTrue(check(records,rewarded={1})(2))
        self.assertFalse(check(records,quests={1:3})(2))
        self.assertTrue(check(records,quests={1:3})(3))
        self.assertFalse(check(records,quests={1:0})(2))
        self.assertFalse(check(records,quests={1:0})(3))

    def test_cycles_missing_quests_and_missing_faction_data_are_unverified_not_recommended(self):
        records=[quest(1,prev=2),quest(2,prev=1),quest(3,prev=99),quest(4,starters=[999])]
        evaluate=check(records)
        for qid in (1,2,3,4):self.assertIsNone(evaluate(qid))
        self.assertIsNone(QuestEligibility({1:quest(1,starters=[68])},{}).for_character({'race':1,'class':8})(1))

    def test_team_class_race_conditions_and_else_group_alternatives(self):
        rows=[condition(1,6,469),condition(1,15,128),
              condition(1,6,67,else_group=1),condition(1,15,1,else_group=1)]
        self.assertTrue(check([quest(1)],conditions=rows)(1))
        self.assertFalse(check([quest(1)],cls=1,conditions=rows)(1))
        self.assertTrue(check([quest(1)],race=2,cls=1,conditions=rows)(1))
        self.assertFalse(check([quest(1)],race=2,conditions=rows)(1))
        self.assertFalse(check([quest(1)],conditions=[condition(1,16,2)])(1))

    def test_negated_and_referenced_conditions_respect_domain_and_or_groups(self):
        self.assertFalse(check([quest(1)],conditions=[condition(1,15,128,negative=True)])(1))
        self.assertTrue(check([quest(1)],cls=1,conditions=[condition(1,15,128,negative=True)])(1))
        rows=[condition(1,-77,0),condition(0,15,128,source=-77)]
        self.assertTrue(check([quest(1)],conditions=rows)(1));self.assertFalse(check([quest(1)],cls=1,conditions=rows)(1))
        self.assertIsNone(check([quest(1)],conditions=[condition(1,-99,0)])(1))
        self.assertIsNone(check([quest(1)],conditions=[condition(1,15,128,script='CustomEligibility')])(1))
        # Level, reputation and other conditions are handled as availability, not arbitrary class exclusions.
        self.assertTrue(check([quest(1)],conditions=[condition(1,27,80,negative=True)])(1))

    def test_explicit_template_friend_and_enemy_lists_override_team_masks(self):
        meta={**META,'faction_templates':{**META['faction_templates'],
          '88':{'faction':88,'group':4,'hostile':2,'friends':[1]},
          '89':{'faction':89,'group':0,'hostile':0,'enemies':[1]}}}
        evaluate=QuestEligibility({1:quest(1,starters=[88]),2:quest(2,starters=[89])},meta).for_character({'race':1,'class':8})
        self.assertTrue(evaluate(1));self.assertFalse(evaluate(2))

    def test_item_start_class_race_and_faction_flags_are_applied(self):
        records=[quest(1,starters=[],items=[[128,-1,0]]),quest(2,starters=[],items=[[-1,-1,1]]),quest(3,starters=[],items=[[0,-1,0]])]
        self.assertTrue(check(records)(1));self.assertFalse(check(records,cls=1)(1));self.assertFalse(check(records)(2));self.assertTrue(check(records,race=2)(2));self.assertFalse(check(records)(3))

    def test_failed_eligibility_cannot_enter_recommendations_or_group_opportunities(self):
        q={'ID':1,'SpecialFlags':0,'Flags':0,'AllowableRaces':0,'AllowableClasses':0,'prev_race':0,'prev_class':0,'MaxLevel':0,
          'PrevQuestID':0,'RequiredSkillID':0,'RequiredSkillPoints':0,'ExclusiveGroup':0,'conditions':0,'QuestLevel':10}
        char=character(quest_eligibility=check([quest(1,starters=[68])]))
        self.assertIsNone(source_state({'kind':'quest','quest':q},char,item()))
