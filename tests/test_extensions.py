import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard
from data_sources import HttpQuestSource, Observation, SourceError
from sql_console import normalize_query, QueryError, SqlConsole, execute_select

TABLES = {('acore_characters', 'characters'), ('acore_characters', 'character_queststatus'),
          ('acore_world', 'quest_template')}


class SqlPolicyTests(unittest.TestCase):
    def test_regular_queries_joins_aggregates_subqueries(self):
        for query in ["SELECT name,level FROM characters WHERE level>5 ORDER BY name",
                      "SELECT COUNT(*) FROM acore_world.quest_template",
                      "SELECT c.name,COUNT(*) FROM characters c JOIN character_queststatus q ON q.guid=c.guid "
                      "GROUP BY c.name HAVING COUNT(*)>1",
                      "SELECT * FROM (SELECT name FROM characters LIMIT 2) c"]:
            sql = normalize_query(query, 'acore_characters', TABLES)
            self.assertTrue(sql.startswith('SELECT * FROM (SELECT'))
            self.assertTrue(sql.endswith('LIMIT 201'))

    def test_writes_commands_files_locks_routines_and_privileged_data_rejected(self):
        malicious = [
            'DELETE FROM characters', 'UPDATE characters SET level=80', 'DROP TABLE characters',
            'SET SESSION TRANSACTION READ WRITE', 'SELECT 1; DELETE FROM characters',
            "SELECT * FROM characters INTO OUTFILE '/tmp/dump'", "SELECT * FROM characters INTO DUMPFILE '/tmp/x'",
            "SELECT LOAD_FILE('/etc/passwd')", "SELECT GET_LOCK('x',10)", 'SELECT SLEEP(1)',
            'SELECT BENCHMARK(999999,MD5(1))', 'SELECT my_function()', 'SELECT acore_world.my_function()',
            'SELECT * FROM mysql.user', 'SELECT * FROM acore_auth.account',
            'SELECT * FROM information_schema.tables', 'SELECT @@GLOBAL.version', 'SELECT @secret',
            'SELECT * FROM characters FOR UPDATE', 'SELECT * FROM characters LOCK IN SHARE MODE',
            'SELECT 1 /*!50000 INTO OUTFILE "/tmp/x" */', 'SELECT /*+ SET_VAR(x=1) */ 1',
            "SELECT 'x'; system touch /tmp/oops", 'SELECT 1\\! whoami',
            'SELECT * FROM unknown_table', 'CALL anything()',
            'WITH RECURSIVE x AS (SELECT 1) SELECT * FROM x']
        for query in malicious:
            with self.subTest(query=query), self.assertRaises(QueryError):
                normalize_query(query, 'acore_characters', TABLES)

    def test_validated_ast_is_qualified_and_comments_cannot_reach_mysql(self):
        sql = normalize_query("SELECT name FROM characters -- harmless comment", 'acore_characters', TABLES)
        self.assertIn('`acore_characters`.`characters`', sql)
        self.assertNotIn('--', sql)

    def test_invalid_query_never_reaches_executor(self):
        calls = []
        console = SqlConsole(catalog_reader=lambda sql: {'rows': sorted(TABLES)},
                             executor=lambda sql: calls.append(sql))
        with self.assertRaises(QueryError):
            console.run('DROP TABLE characters', 'acore_characters')
        self.assertEqual(calls, [])

    def test_prepared_hex_readonly_and_result_limit(self):
        xml = '<?xml version="1.0"?><resultset>' + ''.join(
            f'<row><field name="name">Bot{i}</field></row>' for i in range(201)) + '</resultset>'
        with patch('sql_console.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = xml
            result = execute_select("SELECT name FROM characters")
            script = run.call_args.kwargs['input']
            self.assertIn('TRANSACTION READ ONLY', script)
            self.assertIn('PREPARE dashboard_read FROM @dashboard_sql', script)
            self.assertIn('CONVERT(0x', script)
            self.assertNotIn('SELECT name FROM characters', script)
            self.assertEqual(len(result['rows']), 200)
            self.assertTrue(result['truncated'])


class SourceAndWatchTests(unittest.TestCase):
    def test_provider_swap_preserves_view_and_marks_source(self):
        class LiveFixture:
            def fetch(self, names):
                return Observation([], '2026-10-23T12:00:00+00:00', {
                    'id': 'fixture-live', 'label': 'Fixture', 'live': True, 'save_interval_seconds': None})
        cache = fixture_cache(source=LiveFixture())
        result = cache.get()
        self.assertTrue(result['ok'])
        self.assertEqual(result['snapshot']['source']['id'], 'fixture-live')
        self.assertEqual(len(result['snapshot']['views']['party']['characters']), 6)

    def test_watch_list_normalization_persistence_empty_and_no_database_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'watchlist.json'
            cache = fixture_cache(reader=lambda names: [], watch_file=path)
            self.assertEqual(cache.update_bots(['galen', 'ASTER', 'Galen']), ['Galen', 'Aster'])
            self.assertEqual(json.loads(path.read_text()), ['Galen', 'Aster'])
            self.assertEqual(cache.update_bots([]), [])
            self.assertEqual(cache.get()['snapshot']['views']['bots']['characters'], [])
            for value in [['bad-name'], ['bot;DELETE'], [None], 'Galen', ['Ab'] * 33]:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    cache.update_bots(value)

    def test_live_failures_never_fall_back_to_mysql(self):
        class Broken:
            def fetch(self, names):
                raise SourceError('No live server')
        with patch('dashboard.read_database') as mysql:
            result = fixture_cache(source=Broken()).get()
            self.assertFalse(result['ok'])
            self.assertIsNone(result['snapshot'])
            mysql.assert_not_called()

    def test_live_adapter_rejects_remote_or_embedded_credentials(self):
        for url in ['http://example.com/v1', 'file:///etc/passwd', 'http://user:pass@localhost/v1',
                    'https://localhost/v1', 'http://localhost/v1?token=oops']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                HttpQuestSource(url)

    def test_real_http_live_fixture_and_staleness_and_redirect(self):
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path.startswith('/redirect'):
                    self.send_response(302)
                    self.send_header('Location', 'http://example.com/stolen')
                    self.end_headers()
                    return
                observed = '2000-01-01T00:00:00+00:00' if self.path.startswith('/stale') else (
                    datetime.now(timezone.utc).isoformat())
                body = json.dumps({'schema_version': 1, 'observed_at': observed, 'rows': []}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            self.assertTrue(HttpQuestSource(base + '/v1').fetch(('Aster',)).source['live'])
            for path in ['/stale', '/redirect']:
                with self.subTest(path=path), self.assertRaises(SourceError):
                    HttpQuestSource(base + path).fetch(('Aster',))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class PostBoundaryTests(unittest.TestCase):
    def test_token_and_watchlist_post_and_reject_write_sql(self):
        console = SqlConsole(catalog_reader=lambda sql: {'rows': sorted(TABLES)}, executor=lambda sql: None)
        cache = fixture_cache(reader=lambda names: [])
        server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.handler(cache, 0, console))
        server.RequestHandlerClass = dashboard.handler(cache, server.server_port, console)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            token = json.load(urlopen(base + '/api/session'))['token']

            def post(path, data, supplied=token):
                return urlopen(Request(base + path, data=json.dumps(data).encode(), headers={
                    'Content-Type': 'application/json', 'X-Dashboard-Token': supplied}))

            with self.assertRaises(HTTPError) as error:
                post('/api/watchlist', {'names': ['Aster']}, '')
            self.assertEqual(error.exception.code, 403)
            self.assertEqual(json.load(post('/api/watchlist', {'names': ['Aster']}))['names'], ['Aster'])
            with self.assertRaises(HTTPError) as error:
                post('/api/sql/query', {'query': 'DELETE FROM characters', 'schema': 'acore_characters'})
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


from test_support import fixture_cache

if __name__ == '__main__':
    unittest.main()
