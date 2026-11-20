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

class MailTransactionTests(unittest.TestCase):
    def test_postage_totals_are_sender_scoped(self):
        from transactions import transaction_sql
        sql=transaction_sql({'character':['545'],'kind':['mail_sent_observed']},['Rai'])
        self.assertIn("IF(j.event_kind='mail_sent_observed' AND j.actor_guid=545 AND c.name IN ('Rai'),j.mail_postage,0)",sql)
        self.assertIn('j.counterparty_guid=545',sql)

    def test_mail_attachments_are_searchable_and_exportable(self):
        from transactions import transaction_sql
        sql=transaction_sql({'q':['Linen']},export=True)
        self.assertIn('JSON_TABLE(COALESCE(j.mail_items,JSON_ARRAY())',sql)
        self.assertIn("'mail_subject',j.mail_subject",sql)
        self.assertIn("'mail_items',(SELECT JSON_ARRAYAGG",sql)
