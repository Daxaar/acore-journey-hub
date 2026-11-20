import unittest
from mailbox_view import MailboxProvider,mailbox_sql

class MailboxTests(unittest.TestCase):
    def test_mail_is_scoped_to_recipient_with_read_only_snapshot(self):
        sql=mailbox_sql({'receiver':['545'],'id':['7']})
        self.assertIn('TRANSACTION READ ONLY',sql)
        self.assertIn('m.receiver=545',sql)
        self.assertIn('m.id=7',sql)
        self.assertIn('m.expire_time>UNIX_TIMESTAMP()',sql)
        self.assertNotIn('UPDATE ',sql)
        self.assertNotIn('DELETE ',sql)

    def test_invalid_identifiers_and_duplicate_filters(self):
        for params in ({'receiver':['0']},{'receiver':['1 OR 1=1']},{'receiver':['1','2']},{'receiver':['1'],'page':['10001']}):
            with self.subTest(params=params),self.assertRaises(ValueError):mailbox_sql(params)

    def test_attachments_grouped_and_icons_match_metadata(self):
        rows=[{'kind':'mail_totals','count':2,'unread':2},
              {'kind':'mail','id':1},{'kind':'mail','id':2},
              {'kind':'attachment','mail_id':2,'displayid':10,'id':117,'quantity':3}]
        provider=MailboxProvider(icons={'10':'food'},reader=lambda sql:rows)
        result=provider.get({'receiver':['545']})
        self.assertEqual(result['messages'][0]['attachments'],[])
        self.assertEqual(result['messages'][1]['attachments'][0]['icon'],'food')

    def test_character_search_uses_literal_text(self):
        observed=[]
        provider=MailboxProvider(reader=lambda sql:observed.append(sql) or [])
        provider.characters(q="O'Reilly")
        self.assertNotIn("O'Reilly",observed[0])
        self.assertIn('LOCATE(CONVERT(0x',observed[0])
