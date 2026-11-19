import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from transaction_monitoring import TransactionMonitoring
from transactions import transaction_sql

class MonitoringTests(unittest.TestCase):
    def test_opt_in_and_removal_preserve_other_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TransactionMonitoring(Path(folder)/'monitoring.txt',reader=lambda sql:[{'guid':1}])
            self.assertEqual(store.enabled(),set())
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda guid:store.update(guid,True),[1,2]))
            self.assertEqual(store.enabled(),{1,2})
            store.update(1,False)
            self.assertEqual(store.enabled(),{2})
            self.assertEqual(list(Path(folder).glob('tmp*')),[])

    def test_invalid_or_missing_characters_cannot_be_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TransactionMonitoring(Path(folder)/'monitoring.txt',reader=lambda sql:[])
            for guid,enabled in [(True,True),(1,1),(-1,True),(1,True)]:
                with self.subTest(guid=guid,enabled=enabled),self.assertRaises(ValueError):
                    store.update(guid,enabled)
            self.assertFalse(store.path.exists())

    def test_vendor_kinds_are_filterable(self):
        for kind in ('vendor_purchase','vendor_sale_observed'):
            sql=transaction_sql({'kind':[kind]})
            self.assertIn("j.event_kind='"+kind+"'",sql)
            self.assertIn("'vendor_sell_price',COALESCE(t.SellPrice,0)",sql)

class MonitoringConfigurationTests(unittest.TestCase):
    def test_local_config_persists_shared_path_and_environment_can_override(self):
        import json
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'transaction-journal.json').write_text(json.dumps({'monitoring_file':'shared/monitoring.txt'}))
            with patch('transaction_monitoring.__file__',str(root/'transaction_monitoring.py')),patch.dict(os.environ,{},clear=True):
                self.assertEqual(TransactionMonitoring().path,root/'shared/monitoring.txt')
                with patch.dict(os.environ,{'JOURNEY_HUB_TRANSACTION_MONITORING':'/tmp/override-monitoring.txt'}):
                    self.assertEqual(TransactionMonitoring().path,Path('/tmp/override-monitoring.txt'))
