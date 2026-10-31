"""Journey Hub branding keeps existing installations and environment settings usable."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import connection_config
import deployment_config
from connection import env, mysql_command, database_environment, database_sql
from deploy import check_environment
from package_release import NAME, ARCHIVE_NAME


class JourneyBrandingTests(unittest.TestCase):
    def test_new_old_and_legacy_environment_precedence(self):
        with patch.dict(os.environ, {'JOURNEY_HUB_DB_HOST':'new.invalid',
                                     'CHARACTER_HUB_DB_HOST':'previous.invalid',
                                     'LEMMINGS_DB_HOST':'legacy.invalid'}, clear=True):
            self.assertEqual(env('DB_HOST'), 'new.invalid')
            del os.environ['JOURNEY_HUB_DB_HOST']
            self.assertEqual(env('DB_HOST'), 'previous.invalid')
            del os.environ['CHARACTER_HUB_DB_HOST']
            self.assertEqual(env('DB_HOST'), 'legacy.invalid')

    def test_previous_connection_environment_keeps_credentials_and_schemas(self):
        settings = {'CHARACTER_HUB_DB_MODE':'direct','CHARACTER_HUB_DB_HOST':'old.invalid',
                    'CHARACTER_HUB_DB_USER':'character_hub','CHARACTER_HUB_DB_PASSWORD':'synthetic-secret',
                    'CHARACTER_HUB_WORLD_SCHEMA':'existing_world'}
        with patch.dict(os.environ, settings, clear=True):
            command = mysql_command()
            self.assertIn('--host=old.invalid', command)
            self.assertIn('--user=character_hub', command)
            self.assertNotIn('synthetic-secret', ' '.join(command))
            self.assertEqual(database_environment()['MYSQL_PWD'], 'synthetic-secret')
            self.assertEqual(database_sql('SELECT * FROM acore_world.item_template'), 'SELECT * FROM existing_world.item_template')

    def test_previous_implicit_database_account_is_preserved(self):
        with patch.dict(os.environ, {'CHARACTER_HUB_DB_MODE':'direct'}, clear=True):
            self.assertIn('--user=character_hub', mysql_command())

    def test_saved_connection_and_container_files_are_not_migrated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            connection = root/'connection.json'
            connection.write_text(json.dumps({'db_mode':'direct','db_user':'character_hub'}))
            containers = root/'deployment.json'
            containers.write_text(json.dumps({'db_container':'existing-db','world_container':'existing-world'}))
            before = connection.read_bytes(), containers.read_bytes()
            with patch.object(connection_config, 'CONFIG', connection), patch.object(deployment_config, 'CONFIG', containers), patch.dict(os.environ, {}, clear=True):
                self.assertIn('--user=character_hub', mysql_command())
                self.assertEqual(deployment_config.container('db_container'), 'existing-db')
                with patch.dict(os.environ, {'CHARACTER_HUB_DB_CONTAINER':'previous-db'}):
                    self.assertEqual(deployment_config.container('db_container'), 'previous-db')
                    with patch.dict(os.environ, {'JOURNEY_HUB_DB_CONTAINER':'new-db'}):
                        self.assertEqual(deployment_config.container('db_container'), 'new-db')
            self.assertEqual((connection.read_bytes(),containers.read_bytes()), before)

    def test_setup_still_detects_conflicting_previous_environment(self):
        with patch.dict(os.environ, {'CHARACTER_HUB_DB_HOST':'another.invalid'}, clear=True):
            with self.assertRaises(ValueError):check_environment({'db_mode':'direct','db_host':'expected.invalid'})

    def test_product_branding_and_archive_change_without_folder_changes(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(NAME, 'character-hub')
        self.assertTrue(ARCHIVE_NAME.startswith('azerothcore-journey-hub-v'))
        for page in (root/'static').glob('*.html'):
            text = page.read_text()
            self.assertNotIn('AzerothCore Character Hub', text, page.name)
            self.assertIn('AzerothCore Journey Hub', text, page.name)
