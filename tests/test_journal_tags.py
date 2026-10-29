"""Character/group tags preserve archive data and filter whole entries before pagination."""
import sqlite3
import tempfile
from pathlib import Path
import unittest
from journal import JournalStore,JournalConflict
from test_journal import account,picture,PNG

GROUP={'id':'band','name':'The Band','members':['Aster','Briar']}


class JournalTagTests(unittest.TestCase):
    def test_direct_group_and_legacy_people_matches_are_exact_case_insensitive_and_deduplicated(self):
        store=JournalStore()
        direct=store.save(account(title='Direct',character_tags=['aster',' ASTER ']))
        grouped=store.save(account(title='Group',group_tags=[GROUP]))
        both=store.save(account(title='Both',character_tags=['Aster'],group_tags=[GROUP]))
        legacy=store.save(account(title='Old entry',people='Briar, ASTER and witnesses'))
        store.save(account(title='Different name',people='Asteria',character_tags=['Asteria']))
        result=store.list(character='aStEr')
        self.assertEqual(result['total'],4)
        self.assertEqual({r['id'] for r in result['entries']},{e['id'] for e in [direct,grouped,both,legacy]})
        self.assertEqual(direct['character_tags'],['Aster'])
        self.assertEqual(store.list(character='Briar')['total'],3)
        self.assertEqual(result['characters'],['Aster','Asteria','Briar'])
        store.close()

    def test_group_tag_is_a_historical_snapshot_and_survives_reopening_and_unrelated_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.sqlite3';store=JournalStore(path)
            group={**GROUP,'members':list(GROUP['members'])}
            entry=store.save(account(group_tags=[group],images=[picture()]))
            group['name']='Renamed';group['members'][:]=['Clover']
            store.close();store=JournalStore(path)
            saved=store.get(entry['id']);self.assertEqual(saved['group_tags'],[GROUP])
            self.assertEqual(store.list(character='Briar')['total'],1)
            self.assertEqual(store.list(character='Clover')['total'],0)
            # Older clients omitting tag fields must not erase stored associations.
            payload={k:v for k,v in saved.items() if k not in ('group_tags','character_tags')}
            changed=store.save({**payload,'story':'The story continues.'})
            self.assertEqual(changed['group_tags'],[GROUP])
            self.assertEqual(store.image(entry['screenshots'][0]['id']),('image/png',PNG))
            cleared=store.save({**changed,'group_tags':[]})
            self.assertEqual(cleared['group_tags'],[]);self.assertEqual(store.list(character='Aster')['total'],0)
            store.close()

    def test_tag_search_combines_with_categories_text_order_and_pagination(self):
        store=JournalStore()
        for i in range(52):store.save(account(title=f'Journey {i:02d}',character_tags=['Aster'],group_tags=[GROUP]))
        store.save(account(title='Other',category='Disasters',character_tags=['Aster']))
        result=store.list(search='Band',character='Aster',category='Adventures',order='oldest',page=1)
        self.assertEqual(result['total'],52);self.assertEqual(len(result['entries']),2)
        self.assertEqual(store.list(search='Briar')['total'],52)
        self.assertEqual(store.list(character='Aster',category='Disasters')['total'],1)
        self.assertEqual(store.list(search="'; DELETE FROM entries; --")['total'],0)
        store.close()

    def test_migration_keeps_existing_entry_images_and_revision_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.sqlite3'
            with sqlite3.connect(path) as db:
                db.executescript('''CREATE TABLE entries(id TEXT PRIMARY KEY,title TEXT NOT NULL,entry_date TEXT NOT NULL,
                date_label TEXT NOT NULL,category TEXT NOT NULL,location TEXT NOT NULL,people TEXT NOT NULL,story TEXT NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL,revision INTEGER NOT NULL);
                CREATE TABLE screenshots(id TEXT PRIMARY KEY,entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                name TEXT NOT NULL,mime TEXT NOT NULL,data BLOB NOT NULL);''')
                original=('a'*32,'An old story','2026-10-25','','Adventures','','Aster','Original story','now','now',7)
                db.execute('INSERT INTO entries VALUES (?,?,?,?,?,?,?,?,?,?,?)',original)
                db.execute('INSERT INTO screenshots VALUES (?,?,?,?,?)',('b'*32,'a'*32,'Original.png','image/png',PNG))
            store=JournalStore(path);entry=store.get('a'*32)
            self.assertEqual(entry['character_tags'],[]);self.assertEqual(entry['group_tags'],[])
            self.assertEqual(tuple(store.db.execute('SELECT * FROM entries').fetchone()),original)
            self.assertEqual(entry['revision'],7);self.assertEqual(store.list(character='Aster')['total'],1)
            self.assertEqual(store.image('b'*32),('image/png',PNG));store.close()

    def test_invalid_tags_rejected_before_any_story_change(self):
        store=JournalStore();entry=store.save(account(character_tags=['Aster'],group_tags=[GROUP]))
        for fields in [{'character_tags':['../x']},{'character_tags':'Aster'},{'character_tags':['Aster']*33},
                       {'group_tags':[GROUP,GROUP]},{'group_tags':[{**GROUP,'id':'bad/id'}]},
                       {'group_tags':[{**GROUP,'members':['Aster']*7}]},{'group_tags':[{**GROUP,'name':'<bad>\x00'}]}]:
            with self.subTest(fields=fields),self.assertRaises(ValueError):store.save({**entry,**fields,'story':'Must not save'})
        self.assertEqual(store.get(entry['id']),entry)
        for character in ['Aster;DROP',"' OR 1=1",'x'*13]:
            with self.assertRaises(ValueError):store.list(character=character)
        store.close()

    def test_tags_and_story_roll_back_on_image_failure_and_stale_revision(self):
        store=JournalStore();entry=store.save(account(character_tags=['Aster'],group_tags=[GROUP]))
        store.db.execute("CREATE TRIGGER reject_images BEFORE INSERT ON screenshots BEGIN SELECT RAISE(ABORT,'full'); END")
        with self.assertRaises(sqlite3.IntegrityError):store.save({**entry,'character_tags':['Clover'],'group_tags':[],'story':'Wrong','images':[picture()]})
        self.assertEqual(store.get(entry['id']),entry)
        changed=store.save({**entry,'character_tags':['Clover']})
        with self.assertRaises(JournalConflict):store.save({**entry,'character_tags':[]})
        self.assertEqual(store.get(entry['id']),changed);store.close()

    def test_delete_cascades_tags_and_keeps_other_entries(self):
        store=JournalStore();one=store.save(account(character_tags=['Aster'],group_tags=[GROUP]));two=store.save(account(character_tags=['Clover']))
        store.delete(one['id'],one['revision'])
        for table in ['journal_character_tags','journal_group_tags','journal_group_members']:
            self.assertEqual(store.db.execute('SELECT count(*) FROM '+table+' WHERE entry_id=?',(one['id'],)).fetchone()[0],0)
        self.assertEqual(store.get(two['id'])['character_tags'],['Clover']);store.close()
