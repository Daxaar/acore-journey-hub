"""Connection isolation and fresh-journal release regressions."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from connection import database_sql, database_environment, mysql_command, env
from deploy import bootstrap
from groups import Groups
from journal import JournalStore


class PortableConfigTests(unittest.TestCase):
    def test_direct_connection_keeps_password_out_of_arguments_and_maps_all_schemas(self):
        with patch.dict(os.environ, {'CHARACTER_HUB_DB_MODE':'direct', 'CHARACTER_HUB_DB_HOST':'example.invalid',
                'CHARACTER_HUB_DB_USER':'reader', 'CHARACTER_HUB_DB_PASSWORD':'synthetic-secret',
                'CHARACTER_HUB_CHARACTERS_SCHEMA':'realm_characters', 'CHARACTER_HUB_WORLD_SCHEMA':'realm_world',
                'CHARACTER_HUB_AUTH_SCHEMA':'realm_auth'}, clear=True):
            args=mysql_command()
            self.assertIn('--host=example.invalid',args)
            self.assertIn('--user=reader',args)
            self.assertNotIn('synthetic-secret',' '.join(args))
            self.assertEqual(database_environment()['MYSQL_PWD'],'synthetic-secret')
            self.assertEqual(database_sql('SELECT acore_characters.characters, acore_world.item_template, acore_auth.realmlist'),
                             'SELECT realm_characters.characters, realm_world.item_template, realm_auth.realmlist')
            self.assertIn('--xml',mysql_command(xml=True))

    def test_invalid_schema_and_port_are_rejected(self):
        with patch.dict(os.environ, {'CHARACTER_HUB_WORLD_SCHEMA':'x;DROP DATABASE x'},clear=True):
            with self.assertRaises(ValueError):database_sql('SELECT 1')
        with patch.dict(os.environ, {'CHARACTER_HUB_DB_MODE':'direct','CHARACTER_HUB_DB_PORT':'0'},clear=True):
            with self.assertRaises(ValueError):mysql_command()

    def test_new_environment_names_win_and_legacy_names_still_work(self):
        with patch.dict(os.environ, {'CHARACTER_HUB_REALM_ID':'2','LEMMINGS_REALM_ID':'1'},clear=True):
            self.assertEqual(env('REALM_ID'),'2')
            del os.environ['CHARACTER_HUB_REALM_ID']
            self.assertEqual(env('REALM_ID'),'1')

    def test_requested_group_and_optional_guild_are_not_fixed(self):
        with tempfile.TemporaryDirectory() as folder:
            query=Mock(return_value=[{'name':'Aster'}]);path=Path(folder)/'groups.json'
            bootstrap(path,['Aster'],query,group_name='Explorers',guild_name="Guild's name")
            self.assertEqual(Groups(path).selected()['name'],'Explorers')
            self.assertIn("Guild's name".encode().hex(),query.call_args.args[0])

    def test_new_journal_has_zero_entries_and_no_screenshots(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'journal.sqlite3'
            self.assertFalse(path.exists())
            store=JournalStore(path)
            result=store.list()
            self.assertEqual(result['total'],0)
            self.assertEqual(result['entries'],[])
            import sqlite3
            with sqlite3.connect(path) as db:
                tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                for table in tables:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM "'+table+'"').fetchone()[0],0)
