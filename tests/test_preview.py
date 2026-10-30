"""Preview copies stay independent of live state, including SQLite WAL snapshots."""
from pathlib import Path
from contextlib import ExitStack
import sqlite3
import tempfile
import unittest
from preview import copy_state


class PreviewTests(unittest.TestCase):
    def test_copies_configuration_and_committed_wal_without_sharing_live_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);live=root/'live';app=root/'preview'
            live.mkdir();app.mkdir();(live/'assets').mkdir()
            (live/'groups.json').write_text('{"groups":[]}')
            (live/'network.json').write_text('{"listen":"0.0.0.0"}')
            (live/'assets/profession-metadata.json').write_text('{}')
            (live/'assets/crafting-catalogue.json').write_text('{}')
            with ExitStack() as stack:
                for name in ['activity.sqlite3','journal.sqlite3']:
                    database=stack.enter_context(sqlite3.connect(live/name))
                    database.execute('PRAGMA journal_mode=WAL')
                    database.execute('CREATE TABLE notes(value TEXT)')
                    database.execute("INSERT INTO notes VALUES ('saved')");database.commit()
                copy_state(live,app)
            for name in ['activity.sqlite3','journal.sqlite3']:
                with sqlite3.connect(app/name) as database:
                    self.assertEqual(database.execute('SELECT value FROM notes').fetchone()[0],'saved')
                    database.execute("UPDATE notes SET value='preview'")
                with sqlite3.connect(live/name) as database:
                    self.assertEqual(database.execute('SELECT value FROM notes').fetchone()[0],'saved')
            (app/'groups.json').write_text('preview')
            self.assertEqual((live/'groups.json').read_text(),'{"groups":[]}')
            self.assertFalse((app/'network.json').exists())
            self.assertFalse((app/'assets/crafting-catalogue.json').exists())
            self.assertTrue((app/'assets/profession-metadata.json').exists())
