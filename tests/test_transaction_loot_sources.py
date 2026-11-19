import unittest
from transactions import transaction_sql,get_transactions

class LootSourceTests(unittest.TestCase):
    def test_money_and_separate_source_fields(self):
        sql=transaction_sql({'kind':['loot_money'],'source':['Gnoll'],'zone':['Westfall']})
        for field in ('source_type','source_entry','source_guid','source_name','map_id','map_name','zone_id','zone_name','area_id','area_name'):
            self.assertIn("'"+field+"',j."+field,sql)
        self.assertIn("event_kind='loot_money'",sql)
        self.assertIn("'loot_copper'",sql)
        self.assertIn('j.source_name',sql)
        self.assertIn('j.zone_name',sql)

    def test_source_filters_are_literals_and_support_ids(self):
        sql=transaction_sql({'source':["Gnoll' OR 1=1"],'zone':['40']})
        self.assertNotIn("Gnoll' OR 1=1",sql)
        self.assertIn('LOCATE(CONVERT(0x',sql)
        self.assertIn('j.zone_id=40',sql)
        for key in ('source','zone'):
            with self.assertRaises(ValueError):
                transaction_sql({key:['x\ny']})

    def test_historical_null_sources_are_retained(self):
        rows=[{'kind':'totals','events':1},{'event_kind':'loot','source_name':None,'source_entry':None}]
        result=get_transactions({},reader=lambda sql:rows)
        self.assertIsNone(result['events'][0]['source_name'])
