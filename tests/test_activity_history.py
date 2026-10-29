"""Persistent observations must not invent real event times, abandonment, or group-switch events."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from activity_history import ActivityHistory
from dashboard import SnapshotCache, handler
from test_dashboard import character, quest
from mysql_access import DatabaseError


def saved(name='Aster',guid=1,**values):
    return {**character(name,guid),'reward_history_complete':1,**values}


class HistoryTests(unittest.TestCase):
    def events(self,history,guids=(1,),source='mysql'):
        return history.get(guids,source)['events']

    def test_initial_baseline_unchanged_reads_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'activity.sqlite3'
            h=ActivityHistory(path);rows=[saved(),quest(1)]
            h.observe(rows,'mysql','2026-10-24T10:00:00+00:00')
            h.observe(rows,'mysql','2026-10-24T10:15:00+00:00')
            self.assertEqual(self.events(h),[])
            rows[0]['level']=10
            h.observe(rows,'mysql','2026-10-24T10:30:00+00:00')
            event=self.events(h)[0]
            self.assertEqual(event['kind'],'level')
            self.assertEqual(event['observed'],'2026-10-24T10:30:00+00:00')
            self.assertEqual(event['previous_observed'],'2026-10-24T10:15:00+00:00')
            h.connection.close();reopened=ActivityHistory(path)
            reopened.observe(rows,'mysql','2026-10-24T10:45:00+00:00')
            self.assertEqual(len(self.events(reopened)),1)
            reopened.connection.close()

    def test_objective_and_ready_changes_do_not_need_real_event_timestamps(self):
        h=ActivityHistory();rows=[saved(),quest(1,mob1=1)]
        h.observe(rows,'mysql','first');rows[1]['mob1']=3
        h.observe(rows,'mysql','second')
        self.assertEqual(self.events(h)[0]['kind'],'objective')
        self.assertIn('1 → 3',self.events(h)[0]['message'])
        self.assertIn('Frostmane Headhunter',self.events(h)[0]['message'])
        rows[1]['status']=1;h.observe(rows,'mysql','third')
        self.assertEqual(self.events(h)[0]['kind'],'ready')

    def test_handin_record_disambiguates_departure_and_unseen_quests(self):
        h=ActivityHistory();h.observe([saved(),quest(1)],'mysql','first')
        rows=[saved(),{'kind':'rewarded','guid':1,'quest':287,'active':1},
              {'kind':'rewarded','guid':1,'quest':999,'active':1}]
        h.observe(rows,'mysql','second')
        self.assertEqual([e['kind'] for e in self.events(h)],['handin','handin'])
        self.assertNotIn('left',[e['kind'] for e in self.events(h)])
        self.assertEqual({e['quest'] for e in self.events(h)},{287,999})

    def test_departure_without_new_handin_remains_unknown_and_resets_are_not_completions(self):
        h=ActivityHistory();old=[saved(),quest(1),{'kind':'rewarded','guid':1,'quest':999,'active':1}]
        h.observe(old,'mysql','first')
        h.observe([saved(),{'kind':'rewarded','guid':1,'quest':999,'active':0}],'mysql','second')
        events=self.events(h)
        self.assertEqual(len(events),1);self.assertEqual(events[0]['kind'],'left')
        self.assertIn('reason unknown',events[0]['message'])
        h.observe([saved(),{'kind':'rewarded','guid':1,'quest':999,'active':1}],'mysql','third')
        self.assertEqual(self.events(h)[0]['kind'],'handin')

    def test_group_visibility_source_switches_and_offline_state_do_not_erase_baselines(self):
        h=ActivityHistory();h.observe([saved(),quest(1)],'mysql','first')
        h.observe([saved('Bran',2),quest(2)],'mysql','second')
        h.observe([saved(),quest(1)],'mysql','third')
        self.assertEqual(self.events(h),[])
        h.observe([saved(quest_state_available=False)],'mysql','offline')
        h.observe([saved(),quest(1)],'mysql','online')
        self.assertEqual(self.events(h),[])
        h.observe([saved()], 'live', 'live-first')
        self.assertEqual(self.events(h,source='live'),[])
        self.assertEqual(self.events(h),[])

    def test_incomplete_reward_inputs_do_not_invent_bulk_completions(self):
        h=ActivityHistory();h.observe([saved(reward_history_complete=0),quest(1)],'mysql','first')
        h.observe([saved(),{'kind':'rewarded','guid':1,'quest':287,'active':1}],'mysql','second')
        self.assertEqual([e['kind'] for e in self.events(h)],['left'])

    def test_pagination_filters_and_retention(self):
        h=ActivityHistory();h.observe([saved()],'mysql','first')
        h.connection.executemany('INSERT INTO events(source,guid,name,observed,previous_observed,kind,message) VALUES(?,?,?,?,?,?,?)',
            [('mysql',1,'Aster','seen','prior','level' if i%2 else 'objective',str(i)) for i in range(5010)])
        h.connection.commit();h.observe([saved()],'mysql','second')
        first=h.get([1],'mysql');older=h.get([1],'mysql',offset=50)
        self.assertEqual(first['total'],5000)
        self.assertEqual(len(first['events']),50)
        self.assertGreater(first['events'][-1]['id'],older['events'][0]['id'])
        self.assertTrue(all(e['kind']=='level' for e in h.get([1],'mysql',kind='level')['events']))
        self.assertEqual(h.get([2],'mysql')['total'],0)

    def test_corrupt_storage_is_preserved_and_warning_does_not_break_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.sqlite3';path.write_bytes(b'not a sqlite database')
            cache=fixture_cache(reader=lambda names:[saved(),quest(1)],history_file=path)
            result=cache.get()
            self.assertTrue(result['ok']);self.assertIsNotNone(result['snapshot']['views']['party']['activity']['warning'])
            self.assertEqual(path.read_bytes(),b'not a sqlite database')

    def test_database_failure_does_not_advance_history(self):
        rows=[saved(),quest(1)]
        cache=fixture_cache(reader=lambda names:rows);cache.get()
        rows[0]['level']=10;cache.attempted=float('-inf');cache.get()
        total=cache.history.get([1],'mysql')['total']
        cache.source.fetch=lambda names:(_ for _ in ()).throw(DatabaseError('QA outage'))
        cache.attempted=float('-inf');result=cache.get()
        self.assertFalse(result['ok']);self.assertEqual(cache.history.get([1],'mysql')['total'],total)


class ActivityHttpTests(unittest.TestCase):
    def test_history_endpoint_filters_and_rejects_unknown_parameters(self):
        rows=[saved(),quest(1)];cache=fixture_cache(reader=lambda names:rows);cache.get()
        rows[0]['level']=10;cache.attempted=float('-inf');cache.get()
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(cache,0))
        server.RequestHandlerClass=handler(cache,server.server_port)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            data=json.load(urlopen(base+'/api/activity?view=party&character=Aster&kind=level'))
            self.assertEqual(data['activity']['total'],1)
            for params in ['view=unknown','kind=abandoned','offset=-1','offset=5001','character=Other','view=party&view=bots','sql=anything']:
                with self.subTest(params=params),self.assertRaises(HTTPError) as error:urlopen(base+'/api/activity?'+params)
                self.assertEqual(error.exception.code,400)
        finally:server.shutdown();server.server_close();thread.join()


from test_support import fixture_cache

if __name__=='__main__':unittest.main()
