import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from transactions import export_transactions,transaction_sql
from mysql_access import DatabaseError

class ExportTests(unittest.TestCase):
    def run_export(self,count,declared=None):
        def run(*args,**kwargs):
            self.assertIn("j.event_kind='loot'",kwargs['input'])
            self.assertNotIn('LIMIT 100',kwargs['input'])
            rows=[{'kind':'meta','read_only':1},{'kind':'totals','events':count if declared is None else declared}]
            rows += [{'id':i,'event_uuid':str(i),'displayid':5} for i in range(count)]
            kwargs['stdout'].write('\n'.join(json.dumps(row) for row in rows)+'\n')
            return SimpleNamespace(returncode=0)
        with patch('transactions.mysql_command',return_value=['mysql']),patch('transactions.database_environment',return_value={}),patch('transactions.database_sql',side_effect=lambda sql:sql),patch('transactions.subprocess.run',side_effect=run):
            return export_transactions({'kind':['loot'],'page':['2']},icons={'5':'test_icon'})

    def test_export_covers_multiple_pages_and_preserves_ids(self):
        with self.run_export(225) as download:
            data=json.load(download)
        self.assertEqual(len(data['events']),225)
        self.assertEqual(data['events'][-1]['event_uuid'],'224')
        self.assertEqual(data['events'][0]['icon'],'test_icon')
        self.assertNotIn('page',data['filters'])
        self.assertIn('OFFSET 100',transaction_sql({'page':['2']}))

    def test_incomplete_export_fails_instead_of_silent_truncation(self):
        with self.assertRaises(DatabaseError):self.run_export(100,declared=101)
