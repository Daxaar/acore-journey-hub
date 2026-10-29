import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard
from settings import DEFAULTS, THEMES, FONTS, SettingsStore
from sql_console import SqlConsole, QueryError, execute_select, normalize_query


class SettingsTests(unittest.TestCase):
    def test_safe_defaults_and_independent_copy(self):
        store = SettingsStore()
        values = store.get()
        self.assertTrue(all(values['sql'].values()))
        self.assertEqual(values['appearance'], {'theme': 'forest', 'font': 'classic'})
        values['sql']['row_limit'] = False
        self.assertTrue(store.get()['sql']['row_limit'])

    def test_atomic_persistence_and_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            store = SettingsStore(path)
            values = store.get()
            values['sql']['row_limit'] = False
            values['appearance'] = {'theme': 'frost', 'font': 'modern'}
            store.save(values)
            self.assertEqual(SettingsStore(path).get(), values)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertFalse(path.with_suffix('.tmp').exists())

    def test_all_themes_and_font_presets(self):
        store = SettingsStore()
        for theme in THEMES:
            for font in FONTS:
                values = store.get()
                values['appearance'] = {'theme': theme, 'font': font}
                self.assertEqual(store.save(values)['appearance'], values['appearance'])

    def test_invalid_values_cannot_disable_permanent_guards(self):
        store = SettingsStore()
        for values in [None, {}, {'sql': {}}, {'sql': {'read_only': False}, 'appearance': {}},
                       {**DEFAULTS, 'arbitrary_sql': True},
                       {**DEFAULTS, 'sql': {**DEFAULTS['sql'], 'row_limit': 'false'}},
                       {**DEFAULTS, 'appearance': {'theme': 'custom-css', 'font': 'modern'}}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                store.save(values)
            self.assertEqual(store.get(), DEFAULTS)

    def test_failed_disk_write_preserves_old_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / 'settings.json')
            values = store.get()
            values['sql']['execution_timeout'] = False
            with patch('settings.Path.write_text', side_effect=OSError('Disk unavailable')):
                with self.assertRaises(OSError):
                    store.save(values)
            self.assertEqual(store.get(), DEFAULTS)


class PolicyTests(unittest.TestCase):
    def test_switches_independent_and_query_policy_is_reported(self):
        for key in DEFAULTS['sql']:
            with self.subTest(key=key):
                store = SettingsStore()
                values = store.get()
                values['sql'][key] = False
                store.save(values)
                calls = []

                def execute(sql, **kwargs):
                    calls.append((sql, kwargs))
                    return {'columns': [], 'rows': [], 'truncated': False}

                console = SqlConsole(catalog_reader=lambda sql: {'rows': [('acore_world', 'quest_template')]},
                                     executor=execute, settings=store)
                result = console.run('SELECT ID FROM acore_world.quest_template', 'acore_world')
                query, options = calls[0]
                self.assertEqual('LIMIT 201' in query, key != 'row_limit')
                self.assertEqual(options['row_limit'], None if key == 'row_limit' else 200)
                self.assertEqual(options['execution_timeout'], key != 'execution_timeout')
                self.assertEqual(result['policy'], values['sql'])

    def test_base_table_switch_refreshes_catalog_and_permits_game_views_only(self):
        queries = []

        def catalog(query):
            queries.append(query)
            rows = [('acore_world', 'quest_template')]
            if "TABLE_TYPE='BASE TABLE'" not in query:
                rows.append(('acore_world', 'quest_view'))
            return {'rows': rows}

        store = SettingsStore()
        console = SqlConsole(catalog_reader=catalog, settings=store)
        with self.assertRaises(QueryError):
            normalize_query('SELECT * FROM quest_view', 'acore_world', set(console.catalog()))
        values = store.get()
        values['sql']['base_tables_only'] = False
        store.save(values)
        self.assertIn(('acore_world', 'quest_view'), console.catalog())
        self.assertEqual(len(queries), 2)
        self.assertIn('quest_view', normalize_query('SELECT * FROM quest_view', 'acore_world', set(console.catalog())))
        with self.assertRaises(QueryError):
            normalize_query('SELECT * FROM mysql.user', 'acore_world', set(console.catalog()))

    def test_disabled_limits_mean_no_hidden_row_or_execution_cap(self):
        xml = '<resultset>' + ''.join('<row><field name="n">1</field></row>' for _ in range(240)) + '</resultset>'
        with patch('sql_console.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = xml
            result = execute_select('SELECT 1', row_limit=None, execution_timeout=False)
            self.assertEqual(len(result['rows']), 240)
            self.assertFalse(result['truncated'])
            self.assertIsNone(result['limit'])
            self.assertIsNone(run.call_args.kwargs['timeout'])
            script = run.call_args.kwargs['input']
            self.assertIn('SET SESSION MAX_EXECUTION_TIME=0;', script)
            self.assertIn('SET SESSION TRANSACTION READ ONLY;', script)
            self.assertNotIn('SET GLOBAL', script)

    def test_all_limits_off_still_reject_mutation_files_privileged_schemas_and_functions(self):
        store = SettingsStore()
        values = store.get()
        values['sql'] = dict.fromkeys(values['sql'], False)
        store.save(values)
        executed = []
        console = SqlConsole(catalog_reader=lambda sql: {'rows': [('acore_world', 'quest_template')]},
                             executor=lambda *args, **kwargs: executed.append(args), settings=store)
        for query in ['DROP TABLE quest_template', 'UPDATE quest_template SET ID=1',
                      "SELECT * FROM quest_template INTO OUTFILE '/tmp/no'", 'SELECT GET_LOCK(1,1)',
                      'SELECT * FROM mysql.user', 'SELECT * FROM acore_auth.account',
                      'SET SESSION TRANSACTION READ WRITE']:
            with self.subTest(query=query), self.assertRaises(QueryError):
                console.run(query, 'acore_world')
        self.assertEqual(executed, [])


class SettingsHttpTests(unittest.TestCase):
    def test_closed_browser_connection_does_not_log_a_server_error(self):
        handler = dashboard.handler(fixture_cache(reader=lambda names: []), 8765)
        request = object.__new__(handler)
        request.send_response = Mock()
        request.send_header = Mock()
        request.end_headers = Mock()
        request.wfile = Mock()
        for error in (BrokenPipeError, ConnectionResetError):
            with self.subTest(error=error):
                request.wfile.write.side_effect = error()
                request.send(200, 'text/plain', b'finished')

    def test_settings_submission_requires_token_and_persists_valid_choices_only(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SettingsStore(Path(directory) / 'settings.json')
            cache = fixture_cache(reader=lambda names: [])
            server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.handler(cache, 0, settings=store))
            server.RequestHandlerClass = dashboard.handler(cache, server.server_port, settings=store)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                initial = json.load(urlopen(base + '/api/settings'))['settings']
                self.assertEqual(initial, DEFAULTS)
                token = json.load(urlopen(base + '/api/session'))['token']

                def post(payload, supplied=token):
                    return urlopen(Request(base + '/api/settings', data=json.dumps(payload).encode(), headers={
                        'Content-Type': 'application/json', 'X-Dashboard-Token': supplied}))

                with self.assertRaises(HTTPError) as error:
                    post(initial, '')
                self.assertEqual(error.exception.code, 403)
                chosen = copy.deepcopy(initial)
                chosen['appearance']['theme'] = 'parchment'
                chosen['sql']['row_limit'] = False
                self.assertEqual(json.load(post(chosen))['settings'], chosen)
                self.assertEqual(SettingsStore(store.path).get(), chosen)
                with self.assertRaises(HTTPError) as error:
                    post({**chosen, 'read_only': False})
                self.assertEqual(error.exception.code, 400)
                for path in ['/settings', '/settings.js', '/appearance.js']:
                    self.assertEqual(urlopen(base + path).status, 200)
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + '/settings.json')
                self.assertEqual(error.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


from test_support import fixture_cache

if __name__ == '__main__':
    unittest.main()
