"""Saved direct connections and metadata setup work without Docker or server writes."""
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

import connection_config
import deploy
from connection import env, mysql_command, database_environment, database_sql
from dbc_source import read_dbc_bytes
from prepare_quest_assets import read_dbc
from prepare_armory_assets import dbc
from preview import copy_state


def direct(directory):
    return {'db_mode': 'direct', 'db_host': 'db.example.invalid', 'db_port': 3306,
            'db_user': 'hub_reader', 'db_password': 'synthetic-only;$`value',
            'characters_schema': 'realm_characters', 'world_schema': 'realm_world',
            'auth_schema': 'realm_auth', 'dbc_path': str(directory)}


class NativeInstallTests(unittest.TestCase):
    def test_saved_connection_works_for_subprocesses_without_exports_or_password_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'connection.json'
            config = direct(folder)
            connection_config.save(config, path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with patch.object(connection_config, 'CONFIG', path), patch.dict(os.environ, {}, clear=True):
                args = mysql_command()
                self.assertEqual(args[0], 'mysql')
                self.assertIn('--host=db.example.invalid', args)
                self.assertIn('--port=3306', args)
                self.assertNotIn(config['db_password'], ' '.join(args))
                self.assertEqual(database_environment()['MYSQL_PWD'], config['db_password'])
                self.assertIn('realm_characters.characters', database_sql('SELECT * FROM acore_characters.characters'))
                with patch.dict(os.environ, {'LEMMINGS_DB_HOST':'legacy.invalid', 'JOURNEY_HUB_DB_HOST':'new.invalid'}):
                    self.assertEqual(env('DB_HOST'), 'new.invalid')
                    del os.environ['JOURNEY_HUB_DB_HOST']
                    self.assertEqual(env('DB_HOST'), 'legacy.invalid')

    def test_validation_rejects_bad_settings_without_echoing_values(self):
        for values in [[], {}, {'db_mode':'unknown'}, {'db_mode':'direct','db_port':True},
                       {'db_mode':'direct','db_port':65536}, {'db_mode':'direct','world_schema':'x;DROP'},
                       {'db_mode':'direct','db_password':None}, {'db_mode':'direct','dbc_source':'remote'},
                       {'db_mode':'direct','extra':'synthetic-secret'}]:
            with self.subTest(values=values), self.assertRaises(ValueError) as error:
                connection_config.validate(values)
            self.assertNotIn('synthetic-secret', str(error.exception))

    def test_rerun_preserves_settings_and_refuses_another_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'connection.json'
            config = direct(folder)
            connection_config.save(config, path)
            before = path.read_bytes()
            path.chmod(0o644)
            connection_config.save(config, path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(ValueError):
                connection_config.save({**config, 'db_host':'other.invalid'}, path)
            self.assertEqual(path.read_bytes(), before)

    def test_local_dbc_readers_parse_without_docker_and_preserve_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = struct.pack('<4s4I2I', b'WDBC', 1, 2, 8, 8, 7, 1) + b'\0Sample\0'
            source = root / 'Fixture.dbc'
            source.write_bytes(data)
            settings = {'JOURNEY_HUB_DB_MODE':'direct','JOURNEY_HUB_DBC_PATH':folder}
            with patch.dict(os.environ, settings, clear=True), patch('dbc_source.subprocess.run') as docker:
                rows, text = read_dbc('Fixture')
                self.assertEqual(rows, [(7, 1)])
                self.assertEqual(text(rows[0][1]), 'Sample')
                self.assertEqual(dbc('Fixture', 1), {'7':'Sample'})
                self.assertEqual(source.read_bytes(), data)
                with self.assertRaises(ValueError):read_dbc_bytes('../Fixture')
                with self.assertRaises(ValueError):read_dbc_bytes('Missing')
                docker.assert_not_called()

    def test_docker_and_mixed_dbc_access_are_retained(self):
        for mode in ('docker', 'direct'):
            settings = {'JOURNEY_HUB_DB_MODE':mode,'JOURNEY_HUB_DBC_SOURCE':'docker',
                        'JOURNEY_HUB_WORLD_CONTAINER':'test-world', 'JOURNEY_HUB_DBC_PATH':'/data/dbc'}
            with patch.dict(os.environ, settings, clear=True), patch('dbc_source.subprocess.run', return_value=Mock(stdout=b'DBC')) as run:
                self.assertEqual(read_dbc_bytes('Spell'), b'DBC')
                self.assertEqual(run.call_args.args[0], ['docker','exec','test-world','cat','/data/dbc/Spell.dbc'])

    def test_imported_setup_saves_private_file_and_reuses_it_without_prompts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            supplied = root / 'my-input.json'
            supplied.write_text(json.dumps(direct(folder)))
            path = root / 'connection.json'
            with patch.object(connection_config, 'CONFIG', path), patch.object(deploy, 'CONFIG', root/'deployment.json'), \
                 patch.object(deploy, 'ROOT', root), patch.dict(os.environ, {}, clear=True), \
                 patch('deploy.shutil.which', return_value='/fake/mysql'), patch('deploy.subprocess.run') as run, \
                 patch('builtins.input', side_effect=AssertionError('Unexpected prompt')):
                with patch('sys.argv', ['deploy.py','--config',str(supplied),'--skip-assets']):deploy.main()
                self.assertEqual(connection_config.load(path)['db_host'], 'db.example.invalid')
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                with patch('sys.argv', ['deploy.py','--skip-assets']):deploy.main()
                self.assertEqual(run.call_count, 2)
                self.assertEqual(run.call_args.args[0], ['bash',str(root/'setup.sh'),'--skip-assets'])
                self.assertFalse((root/'deployment.json').exists())
                self.assertFalse((root/'groups.json').exists())

    def test_legacy_container_setup_remains_usable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(connection_config, 'CONFIG', root/'connection.json'), patch.object(deploy, 'CONFIG', root/'deployment.json'), \
                 patch.object(deploy, 'ROOT', root), patch.dict(os.environ, {}, clear=True), \
                 patch('deploy.shutil.which', return_value='/fake/docker'), patch('deploy.subprocess.run'):
                with patch('sys.argv', ['deploy.py','--db-container','realm-db','--world-container','realm-world','--skip-assets']):deploy.main()
                self.assertEqual(json.loads((root/'deployment.json').read_text()), {'db_container':'realm-db','world_container':'realm-world'})
                self.assertFalse((root/'connection.json').exists())

    def test_setup_checks_local_dbc_prerequisites_and_environment_conflicts(self):
        with tempfile.TemporaryDirectory() as folder, patch('deploy.shutil.which', return_value='/fake/mysql'):
            config = direct(folder)
            with self.assertRaises(ValueError):deploy.preflight(connection_config.validate(config))
            for name in ('Spell','ItemDisplayInfo'):(Path(folder)/(name+'.dbc')).write_bytes(b'fixture')
            deploy.preflight(connection_config.validate(config))
            with patch.dict(os.environ, {'JOURNEY_HUB_DB_HOST':'other.invalid'}, clear=True):
                with self.assertRaises(ValueError):deploy.check_environment(connection_config.validate(config))

    def test_interactive_native_setup_hides_password_and_keeps_wizard_side_effect_free(self):
        answers = ['direct', '', '', '', '', '', '', '/tmp/example-dbc']
        with patch('builtins.input', side_effect=answers), patch('deploy.getpass.getpass', return_value='hidden-value') as password:
            config = deploy.interactive_config()
        self.assertEqual(config['db_mode'], 'direct')
        self.assertEqual(config['db_host'], '127.0.0.1')
        self.assertEqual(config['db_port'], '3306')
        self.assertEqual(config['db_password'], 'hidden-value')
        self.assertEqual(config['dbc_path'], '/tmp/example-dbc')
        password.assert_called_once()

    def test_interactive_docker_setup_keeps_existing_default_container_names(self):
        with patch('builtins.input', side_effect=['', '', '']):
            config = deploy.interactive_config()
        self.assertEqual(config, {'db_mode':'docker','db_container':'database','world_container':'worldserver'})

    def test_preview_copies_connection_settings_without_sharing_or_publishing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            live, app = root/'source', root/'preview'
            live.mkdir();app.mkdir()
            connection_config.save(direct(folder), live/'connection.json')
            copy_state(live, app)
            self.assertEqual((live/'connection.json').read_bytes(), (app/'connection.json').read_bytes())
            (app/'connection.json').write_text('{}')
            self.assertEqual(connection_config.load(live/'connection.json')['db_host'], 'db.example.invalid')
            from package_release import sources
            self.assertNotIn('connection.json', sources())
            self.assertIn('examples/connection.json', sources())
