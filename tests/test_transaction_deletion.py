import tempfile
import unittest
from pathlib import Path
from transaction_deletion import TransactionDeletion

class DeletionTests(unittest.TestCase):
    def test_preview_does_not_delete_and_confirm_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            calls=[]
            def reader(sql):
                calls.append(sql)
                return [{'name':'Tester','guid':7,'cutoff':42,'count':3}]
            store=TransactionDeletion(Path(folder)/'monitoring.txt',reader=reader)
            snapshot=store.preview(7)
            self.assertFalse(list(store.folder.glob('*.request')))
            self.assertNotIn('DELETE',calls[0])
            self.assertEqual(store.confirm(snapshot['ticket'])['state'],'pending')
            request=store.folder/(snapshot['ticket']+'.request')
            self.assertEqual(request.read_text().strip(),'7 42')
            store.confirm(snapshot['ticket'])
            self.assertEqual(len(list(store.folder.glob('*.request'))),1)
            (store.folder/(snapshot['ticket']+'.done')).write_text('ok')
            self.assertEqual(store.status(snapshot['ticket'])['state'],'complete')

    def test_invalid_ticket_and_character_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TransactionDeletion(Path(folder)/'monitoring.txt',reader=lambda sql:[])
            for guid in (True,0,'7',7):
                with self.assertRaises(ValueError):store.preview(guid)
            with self.assertRaises(ValueError):store.confirm('../monitoring')
