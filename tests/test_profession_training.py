"""Profession cap upgrades use server offers, base skill, and character level."""
import unittest
from professions import profession_training, PROFESSION_RANK_SPELLS, PROFESSION_CAPS, skills_sql, skill_records
from test_professions import META, ROWS


class ProfessionTrainingTests(unittest.TestCase):
    def offer(self, skill_id=164, index=0, required=50, level=10):
        return dict(kind='profession_training', spell=PROFESSION_RANK_SPELLS[skill_id][index],
                    skill=skill_id, required_skill=required, required_level=level)

    def test_every_profession_and_rank_boundary(self):
        for skill_id in PROFESSION_RANK_SPELLS:
            for index, required in enumerate((50,125,200,275,350)):
                with self.subTest(skill=skill_id, index=index):
                    skill=dict(id=skill_id, value=required, max=PROFESSION_CAPS[index])
                    offer=self.offer(skill_id,index,required,35)
                    result=profession_training(skill,dict(level=35),[offer])
                    self.assertEqual(result['cap'],PROFESSION_CAPS[index+1])
                    self.assertIsNone(profession_training(dict(skill,value=required-1),dict(level=35),[offer]))
                    self.assertIsNone(profession_training(skill,dict(level=34),[offer]))

    def test_unknown_max_final_cap_missing_offer_and_wrong_profession_are_not_flagged(self):
        offer=self.offer()
        for cap in [0,1,50,450,465]:
            self.assertIsNone(profession_training(dict(id=164,value=450,max=cap),dict(level=80),[offer]))
        skill=dict(id=164,value=50,max=75)
        self.assertIsNone(profession_training(skill,dict(level=80),[]))
        self.assertIsNone(profession_training(skill,dict(level=80),[dict(offer,skill=171)]))
        self.assertIsNone(profession_training(skill,dict(level=80),[self.offer(index=1)]))

    def test_server_custom_requirements_and_gathering_level_are_respected(self):
        skill=dict(id=186,value=350,max=375)
        result=profession_training(skill,dict(level=10),[self.offer(186,4,350,0)])
        self.assertEqual(result['rank'],'Grand Master')
        self.assertIsNone(profession_training(skill,dict(level=80),[self.offer(186,4,360,0)]))

    def test_saved_profiles_include_eligible_training_only(self):
        rows=[dict(r,value=50) if r['kind']=='skill' and r['id']==164 else r for r in ROWS]
        skills=skill_records(rows+[self.offer()],META,['Aster'])[0]['skills']
        self.assertEqual(next(s for s in skills if s['id']==164)['training']['rank'],'Journeyman')
        self.assertTrue(all(s['training'] is None for s in skills if s['id']!=164))
        self.assertIn('FROM acore_world.trainer_spell',skills_sql(['Aster']))
        self.assertIn('LIMIT 201',skills_sql(['Aster']))
