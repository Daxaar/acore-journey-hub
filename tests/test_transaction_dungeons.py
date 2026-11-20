import unittest
from unittest.mock import patch
from transactions import transaction_sql

class DungeonFilters(unittest.TestCase):
    @patch('transactions.transaction_locations',return_value={'dungeons':[{'id':36,'name':'The Deadmines'},{'id':43,'name':'Wailing Caverns'}]})
    def test_typed_and_selected_dungeon_filter_same_map(self,locations):
        for value in ('dead','The Deadmines','DEADMINES','36'):
            with self.subTest(value=value):
                self.assertIn('j.map_id IN (36)',transaction_sql({'dungeon':[value]}))
        self.assertIn('1=0',transaction_sql({'dungeon':['Unknown dungeon']}))

    @patch('transactions.transaction_locations',return_value={'dungeons':[{'id':36,'name':'The Deadmines'}]})
    def test_zone_remains_literal_and_filters_reach_export(self,locations):
        sql=transaction_sql({'dungeon':['dead'],'zone':['redridge']},export=True)
        self.assertIn('j.zone_name',sql)
        self.assertIn('j.map_id IN (36)',sql)
        self.assertNotIn('LIMIT 100',sql)
        with self.assertRaises(ValueError):transaction_sql({'dungeon':['x\ny']})
