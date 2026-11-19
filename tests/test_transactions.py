import unittest
from transactions import transaction_sql, get_transactions

class TransactionsTests(unittest.TestCase):
    def test_filters_are_validated(self):
        for params in ({'page':['0']},{'kind':['sale']},{'character':['1 OR 1=1']},
                       {'q':['x','y']},{'from':['not a date']},{'group':['x'],'unknown':['x']}):
            with self.subTest(params=params),self.assertRaises(ValueError):
                transaction_sql(params)
        with self.assertRaises(ValueError):
            transaction_sql({},["Rai' OR 1=1"])

    def test_literal_search_and_party_roles(self):
        sql=transaction_sql({'q':["Copper'_%"],'character':['545'],'kind':['loot']},['Rai'])
        self.assertNotIn("Copper'_%",sql)
        self.assertIn('LOCATE(CONVERT(0x',sql)
        self.assertIn('j.counterparty_guid=545',sql)
        self.assertIn("other.name IN ('Rai')",sql)
        self.assertIn('TRANSACTION READ ONLY',sql)
        self.assertIn('LIMIT 100 OFFSET 0',sql)

    def test_pagination_and_unchanged_event_identity(self):
        events=[{'kind':'totals','events':1},{'event_uuid':'stable-id','event_kind':'loot'}]
        result=get_transactions({'page':['2']},reader=lambda sql:events)
        self.assertEqual(result['events'][0]['event_uuid'],'stable-id')
        self.assertEqual(result['page'],2)
        self.assertIn('OFFSET 100',transaction_sql({'page':['2']}))
