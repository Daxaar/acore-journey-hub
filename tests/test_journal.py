"""Independent durable chronicles, screenshot bounds, atomic edits and HTTP protection."""
import base64
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from unittest.mock import Mock

import dashboard
from journal import JournalStore,JournalConflict,MAX_REQUEST,screenshot

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jH3cAAAAASUVORK5CYII=')


def account(**overrides):
    return {'title':'A traveller’s account','entry_date':'2026-10-24','category':'Adventures',
            'story':'A quiet arrival.\n\n> A letter from home.',**overrides}


def picture():return {'name':'Arrival.png','data':base64.b64encode(PNG).decode()}


class JournalTests(unittest.TestCase):
    def test_persistence_search_categories_chronology_and_images(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.sqlite3';store=JournalStore(path)
            self.assertEqual(store.list()['total'],0)
            first=store.save(account(images=[picture()],location='A quiet valley',people='Aster'))
            store.save(account(title='The guild charter',category='Guild Business',entry_date='2026-10-25'))
            self.assertEqual(store.list()['entries'][0]['title'],'The guild charter')
            self.assertEqual(store.list(order='oldest')['entries'][0]['id'],first['id'])
            self.assertEqual(store.list(search='VALLEY')['total'],1)
            self.assertEqual(store.list(category='Guild Business')['total'],1)
            store.close();store=JournalStore(path)
            self.assertEqual(store.get(first['id'])['story'],first['story'])
            self.assertEqual(store.image(first['screenshots'][0]['id']),('image/png',PNG));store.close()

    def test_edit_conflicts_across_connections_and_atomic_screenshot_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.sqlite3';a=JournalStore(path);b=JournalStore(path)
            entry=a.save(account(images=[picture()]));image=entry['screenshots'][0]['id']
            updated=b.save({**entry,'story':'The extended tale.','remove_images':[image]})
            self.assertEqual(updated['revision'],2);self.assertEqual(updated['created_at'],entry['created_at'])
            with self.assertRaises(JournalConflict):a.save({**entry,'story':'An outdated draft.'})
            with self.assertRaises(JournalConflict):a.delete(entry['id'],entry['revision'])
            with self.assertRaises(LookupError):a.image(image)
            self.assertEqual(a.get(entry['id'])['story'],'The extended tale.');a.close();b.close()

    def test_failed_image_storage_rolls_back_story_change(self):
        store=JournalStore();entry=store.save(account())
        store.db.execute("CREATE TRIGGER reject_images BEFORE INSERT ON screenshots BEGIN SELECT RAISE(ABORT,'full'); END")
        with self.assertRaises(sqlite3.IntegrityError):store.save({**entry,'story':'Must not replace original.','images':[picture()]})
        self.assertEqual(store.get(entry['id'])['story'],entry['story']);store.close()

    def test_delete_removes_only_its_own_entry_and_images(self):
        store=JournalStore();first=store.save(account(images=[picture()]));second=store.save(account(title='Preserved'))
        store.delete(first['id'],first['revision'])
        with self.assertRaises(LookupError):store.get(first['id'])
        with self.assertRaises(LookupError):store.image(first['screenshots'][0]['id'])
        self.assertEqual(store.get(second['id'])['title'],'Preserved');store.close()

    def test_invalid_entries_and_unrelated_images_are_rejected(self):
        store=JournalStore()
        for values in [{'title':''},{'entry_date':'2026-02-30'},{'entry_date':'20261024'},
                       {'category':'Unknown'},{'story':'x'*30001},{'title':'Bad\x00title'},{'id':'../private'}]:
            with self.subTest(values=values),self.assertRaises(ValueError):store.save(account(**values))
        one=store.save(account(images=[picture()]));two=store.save(account())
        with self.assertRaises(ValueError):store.save({**two,'remove_images':[one['screenshots'][0]['id']]})
        with self.assertRaises(ValueError):store.save(account(images=[picture()]*5))
        self.assertEqual(store.get(two['id'])['revision'],1);store.close()

    def test_invalid_images_are_not_interpreted_as_html_or_paths(self):
        for data in [b'<svg onload="alert(1)"></svg>',b'not an image',PNG[:20],b'\xff\xd8garbage\xff\xd9']:
            with self.subTest(data=data),self.assertRaises(ValueError):screenshot({'name':'x.png','data':base64.b64encode(data).decode()})
        with self.assertRaises(ValueError):screenshot({'name':'x.png','data':'!!!'})
        with self.assertRaises(ValueError):screenshot({'name':'x.png','data':'a'*(8*1024*1024)})

    def test_pagination_and_literal_search(self):
        store=JournalStore()
        for index in range(52):store.save(account(title='Record '+str(index)))
        self.assertEqual(len(store.list()['entries']),50)
        self.assertEqual(len(store.list(page=1)['entries']),2)
        self.assertEqual(store.list(search="'; DELETE FROM entries; --")['total'],0)
        self.assertEqual(store.list()['total'],52)
        with self.assertRaises(ValueError):store.list(order='DROP TABLE entries')
        store.close()

    def test_corrupt_journal_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.sqlite3';path.write_bytes(b'original damaged journal')
            store=JournalStore(path)
            with self.assertRaises(sqlite3.DatabaseError):store.list()
            self.assertEqual(path.read_bytes(),b'original damaged journal')


class JournalHttpTests(unittest.TestCase):
    def test_journal_works_without_game_reads_and_protects_mutations_and_images(self):
        reader=Mock(side_effect=AssertionError('No game queries for journal'))
        store=JournalStore();cache=dashboard.SnapshotCache(reader=reader)
        server=ThreadingHTTPServer(('127.0.0.1',0),dashboard.handler(cache,0,journal=store))
        server.RequestHandlerClass=dashboard.handler(cache,server.server_port,journal=store)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            token=json.load(urlopen(base+'/api/session'))['token']
            def post(payload,auth=token):
                return urlopen(Request(base+'/api/journal',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','X-Dashboard-Token':auth}))
            self.assertEqual(json.load(urlopen(base+'/api/journal'))['result']['total'],0)
            with self.assertRaises(HTTPError) as exc:post(account(),'')
            self.assertEqual(exc.exception.code,403)
            entry=json.load(post(account(images=[picture()],story='x'*25000,character_tags=['Aster'],group_tags=[{'id':'qa','name':'QA group','members':['Briar']}])))['entry']
            self.assertEqual(json.load(urlopen(base+'/api/journal?character=aster'))['result']['total'],1)
            self.assertEqual(json.load(urlopen(base+'/api/journal?character=Briar'))['result']['total'],1)
            self.assertEqual(json.load(urlopen(base+'/api/journal?character=Clover'))['result']['total'],0)
            image=entry['screenshots'][0]['id']
            with urlopen(base+'/journal-images/'+image) as response:
                self.assertEqual(response.headers['Content-Type'],'image/png');self.assertEqual(response.read(),PNG)
            changed=json.load(post({**entry,'story':'Revised'}))['entry']
            with self.assertRaises(HTTPError) as exc:post(entry)
            self.assertEqual(exc.exception.code,409)
            for path in ['/journal','/journal.js','/journal.css']:self.assertEqual(urlopen(base+path).status,200)
            for path in ['/journal.sqlite3','/journal.py','/journal-images/../../settings.json']:
                with self.subTest(path=path),self.assertRaises(HTTPError):urlopen(base+path)
            json.load(post({'action':'delete','id':changed['id'],'revision':changed['revision']}))
            with self.assertRaises(HTTPError):urlopen(base+'/journal-images/'+image)
            reader.assert_not_called()
        finally:server.shutdown();server.server_close();thread.join();store.close()
