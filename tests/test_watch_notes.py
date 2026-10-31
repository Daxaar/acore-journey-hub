"""Durable per-name watch notes and protected dashboard-only save transport."""
import json
import base64
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
from watch_notes import WatchNotes, MAX_NOTE_REQUEST
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

    def test_legacy_notes_and_image_only_notes_roundtrip_without_losing_text(self):
        from test_journal import picture, PNG
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'watch-notes.json'
            path.write_text(json.dumps({'Galen':'Existing note','Aster':'Other note'}))
            notes=WatchNotes(path)
            first=notes.save('galen','Existing note',picture())
            image=first['image']
            self.assertNotIn('data',image)
            self.assertEqual(notes.image(image['id']),('image/png',PNG))
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            reloaded=WatchNotes(path)
            self.assertEqual(reloaded.get(),{'Galen':'Existing note','Aster':'Other note'})
            self.assertEqual(reloaded.get_images()['Galen'],image)
            # Text-only clients leave an existing attachment alone.
            self.assertEqual(reloaded.save('Galen','Updated')['image'],image)
            reloaded.save('Galen','')
            self.assertIn('Galen',reloaded.get_images())
            self.assertEqual(WatchNotes(path).image(image['id']),('image/png',PNG))
            reloaded.save('Galen','',None)
            self.assertNotIn('Galen',WatchNotes(path).get())
            with self.assertRaises(LookupError):reloaded.image(image['id'])

    def test_image_replacement_removal_validation_and_failed_save_are_atomic(self):
        from test_journal import picture, PNG
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'watch-notes.json';notes=WatchNotes(path)
            first=notes.save('Galen','Keep this',picture())['image']
            before=path.read_bytes()
            for invalid in [[],[picture(),picture()],{'name':'test.svg','data':base64.b64encode(b'<svg/>').decode()},
                            {'name':'bad.png','data':'invalid!'}, {'name':'large.png','data':'A'*(7*1024*1024)},
                            {**picture(),'unexpected':1}]:
                with self.subTest(invalid_type=type(invalid).__name__),self.assertRaises(ValueError):notes.save('Galen','Changed',invalid)
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(notes.get()['Galen'],'Keep this')
            with patch.object(Path,'replace',side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError):notes.save('Galen','Changed',picture())
            self.assertEqual(notes.get_images()['Galen'],first)
            self.assertEqual(notes.image(first['id']),('image/png',PNG))
            second=notes.save('Galen','Keep this',picture())['image']
            self.assertNotEqual(first['id'],second['id'])
            with self.assertRaises(LookupError):notes.image(first['id'])
            notes.save('Galen','Keep this',None)
            self.assertEqual(WatchNotes(path).get(),{'Galen':'Keep this'})
            self.assertEqual(WatchNotes(path).get_images(),{})

    def test_watch_membership_changes_keep_the_attachment(self):
        from test_journal import picture
        cache=fixture_cache(bots=('Galen',),reader=lambda names:[])
        image=cache.notes.save('Galen','',picture())['image']
        cache.update_bots([]);cache.update_bots(['Galen'])
        self.assertEqual(cache.notes.get_images()['Galen'],image)

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
            from test_journal import picture, PNG
            result=json.load(post({'name':'Galen','text':'Hello','image':picture()}))
            image=result['note']['image']
            with urlopen(base+image['url']) as response:
                self.assertEqual(response.headers['Content-Type'],'image/png')
                self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
                self.assertEqual(response.read(),PNG)
            session=json.load(urlopen(base+'/api/session'))
            self.assertEqual(session['note_images']['Galen'],image)
            self.assertNotIn('data',session['note_images']['Galen'])
            with self.assertRaises(HTTPError) as error:post({'name':'Galen','text':'Keep','images':[picture(),picture()]})
            self.assertEqual(error.exception.code,400)
            with self.assertRaises(HTTPError) as error:post({'name':'Galen','text':'Keep','image':picture()},'')
            self.assertEqual(error.exception.code,403)
            # The upload route accepts actual image-sized JSON, not the normal 20 KB cap.
            large=picture();large['data']=base64.b64encode(PNG[:-12]+b'X'*30000+PNG[-12:]).decode()
            self.assertTrue(json.load(post({'name':'Galen','text':'','image':large}))['ok'])
            json.load(post({'name':'Galen','text':'Hello','image':None}))
            with self.assertRaises(HTTPError) as error:urlopen(base+image['url'])
            self.assertEqual(error.exception.code,404)
            with self.assertRaises(HTTPError) as error:post({'name':'Galen','text':'x'*2001})
            self.assertEqual(error.exception.code,400)
            with self.assertRaises(HTTPError) as error:urlopen(base+'/watch-notes.json')
            self.assertEqual(error.exception.code,404)
        finally:server.shutdown();server.server_close();thread.join()


from test_support import fixture_cache

if __name__=='__main__':unittest.main()
