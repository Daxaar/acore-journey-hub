"""Inventory ownership/slot semantics and fixed read-only transport boundaries."""
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from armory import ArmoryProvider, armory_sql, build_inventory
from mysql_access import DatabaseError


def item(guid, bag, slot, **overrides):
    value = {'kind': 'item', 'guid': guid, 'owner': 7, 'bag': bag, 'slot': slot,
             'entry': 123, 'name': 'Test item', 'count': 1, 'ContainerSlots': 0}
    value.update(overrides)
    return value


class InventoryTests(unittest.TestCase):
    def view(self, *items, metadata=None):
        return build_inventory([{'kind':'character','guid':7,'name':'Aster'}, *items], metadata or {})

    def test_equipped_bag_guid_links_contents_and_spare_bag_adds_no_capacity(self):
        data = self.view(item(900,0,19,ContainerSlots=8), item(901,900,3),
                         item(902,0,23,ContainerSlots=24), item(903,0,15))
        self.assertEqual(data['capacity'], 24)
        self.assertEqual(data['occupied'], 2)
        self.assertEqual(data['bags'][1]['slots'][3]['guid'], 901)
        self.assertEqual(data['equipment'][15]['item']['guid'], 903)
        self.assertEqual(data['warnings'], [])

    def test_bank_keyring_and_bank_bag_are_not_carried(self):
        data = self.view(item(800,0,67,ContainerSlots=24), item(801,800,0),
                         item(802,0,39), item(803,0,86), item(804,0,118))
        self.assertEqual(data['occupied'], 0)
        self.assertEqual(data['capacity'], 16)
        self.assertEqual(data['stored_records'], 5)
        self.assertEqual(data['warnings'], [])

    def test_bank_slots_and_bank_bag_contents_are_separate(self):
        data = self.view(item(800,0,67,ContainerSlots=8), item(801,800,7), item(802,0,66))
        self.assertEqual(data['bank'][0]['slots'][27]['guid'],802)
        self.assertEqual(data['bank'][1]['slots'][7]['guid'],801)
        self.assertEqual(sum(b['occupied'] for b in data['bank']),2)
        self.assertEqual(data['occupied'],0)
        self.assertEqual(len(data['bank']),8)

    def test_guild_items_use_tab_and_slot_without_character_ownership(self):
        rows = [{'kind':'character','guid':7,'name':'Aster'},
                {'kind':'guild','id':2,'name':'Explorers','money':100},
                {'kind':'guild_tab','id':0,'name':'Supplies'},
                {'kind':'guild_tab','id':1,'name':'Empty'},
                item(900,0,97,kind='guild_item',owner=0)]
        data = build_inventory(rows,{})
        self.assertEqual(data['guild']['name'],'Explorers')
        self.assertEqual(data['guild_bags'][0]['slots'][97]['guid'],900)
        self.assertEqual(data['guild_bags'][1]['occupied'],0)
        self.assertEqual(data['warnings'],[])
        self.assertIsNone(self.view()['guild'])
        self.assertEqual(self.view()['guild_bags'],[])

    def test_unknown_bag_and_out_of_range_contents_warn(self):
        data = self.view(item(900,0,19,ContainerSlots=8), item(901,900,8), item(902,19,0))
        self.assertEqual(data['occupied'], 0)
        self.assertIn('2 records', ' '.join(data['warnings']))

    def test_missing_template_owner_and_capacity_are_not_silently_accepted(self):
        data = self.view(item(900,0,19,ContainerSlots=200), item(901,0,23,name=None,owner=99))
        self.assertEqual(data['capacity'],16)
        self.assertGreaterEqual(len(data['warnings']),2)
        self.assertIn('Unknown item',data['bags'][0]['slots'][0]['name'])

    def test_suffix_and_saved_enchantment_labels(self):
        data = self.view(item(900,0,15,displayid=22,randomPropertyId=-4,enchantments='88 0 0 0 0 0'),
                         metadata={'icons':{'22':'inv_sword_01'},'suffixes':{'4':'of Strength'},
                                   'enchants':{'88':'+2 Strength'}})
        value = data['equipment'][15]['item']
        self.assertEqual(value['name'],'Test item of Strength')
        self.assertEqual(value['enchant_labels'],['+2 Strength'])
        self.assertEqual(value['icon'],'inv_sword_01')

    def test_zero_capacity_missing_bags_still_show_backpack(self):
        data = self.view()
        self.assertEqual(len(data['bags']),5)
        self.assertEqual([b['capacity'] for b in data['bags']],[16,0,0,0,0])
        self.assertEqual(data['occupied'],0)

    def test_no_partial_result_on_limit(self):
        with self.assertRaises(DatabaseError):
            self.view(*[item(i,0,23) for i in range(1001)])

    def test_fixed_bounds_and_readonly_independent_of_explorer_settings(self):
        sql = armory_sql('Aster')
        for clause in ('MAX_EXECUTION_TIME=3000','CONSISTENT SNAPSHOT, READ ONLY','LIMIT 1001','COMMIT;'):
            self.assertIn(clause,sql)
        self.assertIn('0x4173746572',sql)
        for name in ['',"Aster'; DROP TABLE x",'../Aster','Aster Bran']:
            with self.assertRaises(ValueError):
                armory_sql(name)

    def test_provider_retains_no_other_character_on_failed_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            reader = lambda name: [{'kind':'character','guid':7,'name':'Aster'}] if name == 'Aster' else []
            provider = ArmoryProvider(Path(directory), reader)
            self.assertEqual(provider.get('Aster')['character']['name'],'Aster')
            with self.assertRaises(LookupError): provider.get('Missing')
            with patch('armory.urllib.request.urlopen') as network:
                for name in ['../secret','inv_bag/../../x','https://example.com','unknown']:
                    with self.assertRaises(LookupError): provider.icon(name)
                network.assert_not_called()


if __name__ == '__main__': unittest.main()
