"""Meaningful changes must be distinguished from fresh queries and first observations."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from observed_changes import ObservedChanges
from dashboard import SnapshotCache
from mysql_access import DatabaseError
from armory import ArmoryProvider
from client_models import ClientModels, client_path, array, blp


class ChangeTests(unittest.TestCase):
    def test_baseline_queries_changes_and_independent_characters(self):
        tracker=ObservedChanges()
        self.assertEqual(tracker.observe('Aster',{'count':1},'first'),
                         {'monitoring_since':'first','last_observed_change_at':None})
        self.assertIsNone(tracker.observe('Aster',{'count':1},'second')['last_observed_change_at'])
        self.assertEqual(tracker.observe('Aster',{'count':2},'third')['last_observed_change_at'],'third')
        self.assertEqual(tracker.observe('Aster',{'count':2},'fourth')['last_observed_change_at'],'third')
        self.assertIsNone(tracker.observe('Bran',{'count':99},'fifth')['last_observed_change_at'])

    def test_quest_cache_does_not_count_refresh_timestamps_and_preserves_on_failure(self):
        rows=[{'kind':'character','guid':1,'name':'Aster','race':7,'class':1,'level':9,'xp':1,'online':0,'zone':1,'logout_time':0}]
        cache=fixture_cache(reader=lambda names:rows)
        first=cache.get()['snapshot'];self.assertIsNone(first['changes']['party']['last_observed_change_at'])
        cache.attempted=float('-inf');second=cache.get()['snapshot']
        self.assertEqual(first['changes'],second['changes'])
        rows[0]['xp']=2;cache.attempted=float('-inf');changed=cache.get()['snapshot']
        self.assertEqual(changed['changes']['party']['last_observed_change_at'],changed['last_success'])
        cache.source.fetch=lambda names: (_ for _ in ()).throw(DatabaseError('test outage'))
        cache.attempted=float('-inf');failed=cache.get()
        self.assertFalse(failed['ok']);self.assertEqual(failed['snapshot']['changes'],changed['changes'])
        cache.update_bots(['Bran']);self.assertEqual(cache.changes.states,{})

    def test_inventory_queries_exclude_refresh_time_and_track_count_changes(self):
        rows=[{'kind':'character','guid':7,'name':'Aster'},
              {'kind':'item','guid':8,'owner':7,'bag':0,'slot':23,'name':'Apple','count':1}]
        with tempfile.TemporaryDirectory() as directory:
            provider=ArmoryProvider(Path(directory),lambda name:rows)
            first=provider.get('Aster')['changes']
            provider.cached.clear();self.assertEqual(provider.get('Aster')['changes'],first)
            rows[1]['count']=2;provider.cached.clear()
            self.assertIsNotNone(provider.get('Aster')['changes']['last_observed_change_at'])


class ModelTests(unittest.TestCase):
    def test_client_path_windows_linux_and_reject_invalid_paths(self):
        self.assertEqual(str(client_path(r'C:\Games\WoW')),'/mnt/c/Games/WoW')
        self.assertEqual(str(client_path('/mnt/d/Games/WoW')),'/mnt/d/Games/WoW')
        for value in ['', 'relative', '../Data', 'C:\\Games\\..\\secret', '//server/share','/tmp/\x00x',None]:
            with self.assertRaises(ValueError):client_path(value)

    def test_config_validation_is_strict(self):
        for value in [None,{}, {'enabled':1,'client_path':'/tmp'}, {'enabled':False,'client_path':None},
                      {'enabled':True,'client_path':''}, {'enabled':True,'client_path':123}]:
            with self.assertRaises(ValueError):ClientModels.validate(value)

    def test_missing_and_corrupt_assets_are_normal_fallbacks(self):
        appearance={'race':7,'gender':1,'skin':2,'face':1,'hairStyle':2,'hairColor':7,'facialStyle':1}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'Data').mkdir()
            provider=ClientModels(root,builder=lambda path,c:(_ for _ in ()).throw(ValueError('corrupt model')))
            provider.save({'enabled':True,'client_path':directory})
            self.assertTrue(provider.get(appearance)['pending'])
            # Preparation is one optional background worker; wait on its actual lock/state, bounded.
            import time
            for _ in range(100):
                with provider.lock:active=provider.active
                if not active:break
                time.sleep(.01)
            self.assertEqual(provider.get(appearance),{'available':False,'pending':False})
            provider.save({'enabled':False,'client_path':directory})
            self.assertEqual(provider.get(appearance),{'available':False,'pending':False})
            self.assertEqual(json.loads((root/'client-models.json').read_text()),provider.get_config())

    def test_config_http_requires_token_and_rejects_invalid_input(self):
        from http.server import ThreadingHTTPServer
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        import dashboard
        with tempfile.TemporaryDirectory() as directory:
            provider=ClientModels(Path(directory))
            with patch('dashboard.ClientModels',return_value=provider):
                cache=fixture_cache(reader=lambda names:[])
                server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.handler(cache,0))
                server.RequestHandlerClass=dashboard.handler(cache,server.server_port)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                token=json.load(urlopen(base+'/api/session'))['token']
                value={'enabled':False,'client_path':directory}
                def post(value,token):
                    return Request(base+'/api/models/config',data=json.dumps(value).encode(),headers={
                        'Content-Type':'application/json','X-Dashboard-Token':token})
                with self.assertRaises(HTTPError) as denied:urlopen(post(value,''))
                self.assertEqual(denied.exception.code,403)
                with self.assertRaises(HTTPError) as invalid:
                    urlopen(post({'enabled':False,'client_path':None},token))
                self.assertEqual(invalid.exception.code,400)
                self.assertTrue(json.load(urlopen(post(value,token)))['ok'])
                self.assertEqual(json.load(urlopen(base+'/api/models/config'))['config'],value)
                with self.assertRaises(HTTPError) as invalid:urlopen(base+'/api/model?race=7')
                self.assertEqual(invalid.exception.code,400)
            finally:
                server.shutdown();server.server_close();worker.join()

    def test_untrusted_binary_lengths_fail_closed(self):
        import struct
        with self.assertRaises(ValueError):array(struct.pack('<II',500000,8),0,'f',100)
        with self.assertRaises(ValueError):blp(b'not a supported texture')


from test_support import fixture_cache

if __name__=='__main__':unittest.main()
