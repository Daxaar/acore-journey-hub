"""Durable per-name watch notes and protected dashboard-only save transport."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from watch_notes import WatchNotes
from dashboard import SnapshotCache,handler


class NoteTests(unittest.TestCase):
    def test_paragraph_persists_with_normalized_name_and_empty_note_removes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'watch-notes.json';notes=WatchNotes(path)
            text='First seen in Dun Morogh at level 8.\nFriendly warrior — keep an eye on this bot.'
            self.assertEqual(notes.save('Galen',text),{'name':'Galen','text':text})
            self.assertEqual(WatchNotes(path).get(),{'Galen':text})
            notes.save('Aster','Another note')
            notes.save('Galen',' \n ')
            self.assertEqual(WatchNotes(path).get(),{'Aster':'Another note'})

    def test_bad_input_is_rejected_without_changing_existing_notes(self):
        notes=WatchNotes();notes.save('Galen','Keep this')
        for name,text in [(None,'x'),('../x','x'),('Galen',None),('Galen','x'*2001),('Galen','x\x00'),('Galen','\ud800')]:
            with self.subTest(name=name),self.assertRaises(ValueError):notes.save(name,text)
            self.assertEqual(notes.get(),{'Galen':'Keep this'})

    def test_failed_save_preserves_memory_and_file_and_bad_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'watch-notes.json';notes=WatchNotes(path);notes.save('Galen','Original')
            with patch.object(Path,'replace',side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError):notes.save('Galen','Replacement')
            self.assertEqual(notes.get(),{'Galen':'Original'})
            self.assertEqual(WatchNotes(path).get(),notes.get())
            path.write_text('invalid json')
            with self.assertRaises(ValueError):WatchNotes(path)
            self.assertEqual(path.read_text(),'invalid json')

    def test_remove_and_readd_watch_member_preserves_note_and_does_not_touch_quests(self):
        calls=[]
        cache=fixture_cache(bots=('Galen',),reader=lambda names:calls.append(names) or [])
        cache.notes.save('Galen','Met at level 8')
        cache.update_bots([]);cache.update_bots(['Galen'])
        self.assertEqual(cache.notes.get()['Galen'],'Met at level 8')
        self.assertEqual(calls,[])

    def test_note_http_needs_token_and_notes_are_not_served_as_files(self):
        cache=fixture_cache(reader=lambda names:[])
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(cache,0));server.RequestHandlerClass=handler(cache,server.server_port)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
        try:
            token=json.load(urlopen(base+'/api/session'))['token']
            def post(payload,supplied=token):
                return urlopen(Request(base+'/api/watch-notes',data=json.dumps(payload).encode(),headers={
                    'Content-Type':'application/json','X-Dashboard-Token':supplied}))
            with self.assertRaises(HTTPError) as error:post({'name':'Galen','text':'Hello'},'')
            self.assertEqual(error.exception.code,403)
            self.assertTrue(json.load(post({'name':'Galen','text':'Hello'}))['ok'])
            self.assertEqual(json.load(urlopen(base+'/api/session'))['notes'],{'Galen':'Hello'})
            with self.assertRaises(HTTPError) as error:post({'name':'Galen','text':'x'*2001})
            self.assertEqual(error.exception.code,400)
            with self.assertRaises(HTTPError) as error:urlopen(base+'/watch-notes.json')
            self.assertEqual(error.exception.code,404)
        finally:server.shutdown();server.server_close();thread.join()


from test_support import fixture_cache

if __name__=='__main__':unittest.main()
