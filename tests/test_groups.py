"""Named roster persistence, validation, comparison membership and HTTP boundaries."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from groups import Groups
import dashboard
from test_dashboard import character, quest
from mysql_access import DatabaseError


class GroupTests(unittest.TestCase):
    def test_persistence_of_creation_edit_and_last_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'groups.json'
            groups = seeded_groups(path)
            groups.update({'action':'create','name':'Weekend','members':[' bran ', 'Aster']})
            selected = groups.data['selected']
            self.assertEqual(Groups(path).selected()['members'], ['Bran','Aster'])
            groups.update({'action':'edit','id':selected,'name':'Duo','members':['Bran']})
            self.assertEqual(Groups(path).selected()['name'], 'Duo')
            groups.update({'action':'select','id':'band'})
            self.assertEqual(Groups(path).selected()['name'], 'The Band')
            groups.update({'action':'delete','id':'band'})
            self.assertEqual(Groups(path).data['selected'], selected)
            with self.assertRaises(ValueError):
                groups.update({'action':'delete','id':selected})
            self.assertEqual(Groups(path).selected()['name'], 'Duo')

    def test_invalid_members_and_names_do_not_change_saved_state(self):
        groups = seeded_groups()
        original = json.dumps(groups.data)
        for name, members in [('', ['Aster']), ('x'*61,['Aster']), ('Valid', []),
                              ('Valid',['Aster']*7), ('Valid',['Aster','aster']),
                              ('Valid',['../Aster']), ('Valid',[None]), ('The Band',['Bran']),
                              ('Valid', 'Aster')]:
            with self.subTest(name=name,members=members), self.assertRaises(ValueError):
                groups.update({'action':'create','name':name,'members':members})
            self.assertEqual(json.dumps(groups.data), original)
        with self.assertRaises(ValueError):
            groups.update({'action':'select','id':'missing'})

    def test_storage_failure_retains_existing_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            groups = seeded_groups(Path(directory)/'groups.json')
            with patch.object(Path, 'write_text', side_effect=OSError('unavailable')):
                with self.assertRaises(OSError):
                    groups.update({'action':'create','name':'Solo','members':['Aster']})
            self.assertEqual(groups.data['selected'],'band')

    def test_comparison_uses_only_selected_group_and_preserves_order(self):
        calls = []
        rows = [character('Aster',1),character('Bran',2),quest(1),quest(2,mob1=2)]
        def reader(names):
            calls.append(names)
            return rows
        cache = fixture_cache(bots=(),reader=reader)
        cache.get()
        cache.update_groups({'action':'create','name':'Duo','members':['Bran','Aster']})
        duo = cache.get()['snapshot']['views']['party']
        self.assertEqual(calls[-1],('Bran','Aster'))
        self.assertEqual([c['name'] for c in duo['characters']],['Bran','Aster'])
        self.assertEqual(duo['summary']['shared'],1)
        cache.update_groups({'action':'create','name':'Solo','members':['Bran']})
        solo = cache.get()['snapshot']['views']['party']
        self.assertEqual(solo['summary']['shared'],0)
        self.assertEqual(solo['summary']['behind'],0)
        self.assertEqual(solo['summary']['active'],1)
        cache.update_groups({'action':'select','id':'band'})
        cache.source.fetch = lambda names: (_ for _ in ()).throw(DatabaseError('outage'))
        failed=cache.get()
        self.assertFalse(failed['ok'])
        self.assertIsNone(failed['snapshot'])

    def test_groups_http_requires_token_and_rejects_invalid_configuration(self):
        cache=fixture_cache(reader=lambda names:[])
        server=ThreadingHTTPServer(('127.0.0.1',0), dashboard.handler(cache,0))
        server.RequestHandlerClass=dashboard.handler(cache,server.server_port)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            session=json.load(urlopen(base+'/api/session'))
            self.assertEqual(session['groups']['selected'],'band')
            def post(payload,token=session['token']):
                return urlopen(Request(base+'/api/groups',data=json.dumps(payload).encode(),headers={
                    'Content-Type':'application/json','X-Dashboard-Token':token}))
            payload={'action':'create','name':'Solo','members':['Aster']}
            with self.assertRaises(HTTPError) as error: post(payload,'')
            self.assertEqual(error.exception.code,403)
            with self.assertRaises(HTTPError) as error: post({**payload,'members':[]})
            self.assertEqual(error.exception.code,400)
            result=json.load(post(payload))
            self.assertEqual(result['groups']['groups'][-1]['name'],'Solo')
            snapshot=json.load(urlopen(base+'/api/snapshot'))['snapshot']
            self.assertEqual(len(snapshot['views']['party']['characters']),1)
        finally:
            server.shutdown();server.server_close();thread.join()


from test_support import fixture_cache, seeded_groups

if __name__ == '__main__': unittest.main()
