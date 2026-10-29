"""Isolated quest semantics, stale-snapshot and HTTP boundary tests; no live server changes."""

import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dashboard


def character(name, guid):
    return {'kind': 'character', 'name': name, 'guid': guid, 'class': 1, 'race': 7,
            'level': 9, 'xp': 120, 'zone': 1, 'online': 0}


def quest(guid, **overrides):
    row = {'kind': 'quest', 'guid': guid, 'id': 287, 'status': 3, 'title': 'Frostmane Hold', 'level': 10,
           'template_found': 1, 'target1': 1123, 'target_count1': 5, 'mob1': 5,
           'target_name1': 'Frostmane Headhunter', 'area': 'Fully explore Frostmane Hold',
           'special_flags': 2, 'explored': 0}
    row.update(overrides)
    return row


class QuestTests(unittest.TestCase):
    def test_frostmane_kills_do_not_hide_incomplete_exploration(self):
        data = dashboard.build_view([character('Aster', 1), quest(1)], FIXTURE_PARTY)
        q = data['quests'][0]
        self.assertEqual(q['progress'][0]['status'], 'active')
        self.assertEqual(q['progress'][0]['counts'], {'target1': 5, 'exploration': 0})
        self.assertEqual(data['summary']['ready'], 0)
        self.assertEqual(len(data['characters']), 6)
        self.assertFalse(data['characters'][1]['found'])

    def test_saved_status_is_authoritative_in_both_directions(self):
        for status, explored, expected in [(1, 0, 'ready'), (3, 1, 'active'), (5, 1, 'failed')]:
            with self.subTest(status=status):
                data = dashboard.build_view([character('Aster', 1), quest(1, status=status, explored=explored)],
                                            ('Aster',))
                self.assertEqual(data['quests'][0]['progress'][0]['status'], expected)

    def test_behind_comparison_uses_matching_objective_and_ignores_missing_members(self):
        rows = [character('Aster', 1), character('Bran', 2), character('Fenn', 3),
                quest(1), quest(2, mob1=2)]
        q = dashboard.build_view(rows, ('Aster', 'Bran', 'Fenn'))['quests'][0]
        self.assertTrue(q['shared'])
        self.assertFalse(q['progress'][0]['behind'])
        self.assertEqual(q['progress'][1]['behind_objectives'], ['target1'])
        self.assertEqual(q['progress'][2]['status'], 'missing')
        self.assertFalse(q['progress'][2]['behind'])

    def test_ready_member_flags_other_active_member_even_with_no_numeric_counters(self):
        rows = [character('Aster', 1), character('Bran', 2),
                quest(1, special_flags=0, target1=0, status=1), quest(2, special_flags=0, target1=0)]
        q = dashboard.build_view(rows, ('Aster', 'Bran'))['quests'][0]
        self.assertTrue(q['progress'][1]['behind'])
        self.assertEqual(q['objectives'][0]['kind'], 'event')

    def test_rewarded_is_not_confused_with_missing_or_repeatable_active(self):
        rows = [character('Aster', 1), character('Bran', 2), quest(1),
                {'kind': 'rewarded', 'guid': 2, 'quest': 287}]
        data = dashboard.build_view(rows, ('Aster', 'Bran'))
        self.assertEqual(data['quests'][0]['progress'][1]['status'], 'rewarded')
        rows.append(quest(2))
        self.assertEqual(dashboard.build_view(rows, ('Aster', 'Bran'))['quests'][0]['progress'][1]['status'], 'active')

    def test_surplus_collection_does_not_mark_finished_collector_behind(self):
        rows = [character('Aster', 1), character('Bran', 2),
                quest(1, item_id1=44, item_count1=3, item1=3),
                quest(2, item_id1=44, item_count1=3, item1=8)]
        data = dashboard.build_view(rows, ('Aster', 'Bran'))
        self.assertFalse(data['quests'][0]['attention'])

    def test_negative_targets_casts_items_and_unknown_requirements(self):
        data = dashboard.objectives(quest(1, target1=-42, target_name1='Ancient chest', item_id6=55,
                                         item_count6=4, item6=2, faction=99, reputation_required=300))
        self.assertEqual(data[0]['kind'], 'interact')
        self.assertEqual(next(o for o in data if o['key'] == 'item6')['current'], 2)
        self.assertIsNone(next(o for o in data if o['key'] == 'reputation')['current'])
        self.assertEqual(dashboard.objectives(quest(1, special_flags=32))[0]['kind'], 'interact')
        self.assertIn('exploration', [o['kind'] for o in dashboard.objectives(
            quest(1, special_flags=0, has_area_trigger=1))])

    def test_names_cannot_inject_sql_and_no_browser_input_is_needed(self):
        for name in ["Aster');DROP TABLE x;--", 'Aster Bran', '', '../env']:
            with self.assertRaises(ValueError):
                dashboard.snapshot_sql([name])
        sql = dashboard.snapshot_sql(FIXTURE_PARTY)
        self.assertIn('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;', sql)
        self.assertIn('SET SESSION TRANSACTION READ ONLY;', sql)
        for forbidden in ['INSERT ', 'UPDATE ', 'DELETE ', 'CREATE ', 'ALTER ', 'GRANT ']:
            self.assertNotIn(forbidden, sql.upper())


class CacheTests(unittest.TestCase):
    def test_failure_keeps_success_timestamp_and_data_and_recovers(self):
        rows = [character('Aster', 1), quest(1)]
        with patch('dashboard.time.monotonic', return_value=0) as clock:
            cache = fixture_cache(reader=lambda names: rows)
            first = cache.get()
            clock.return_value = 3

            def fail(names):
                raise dashboard.DatabaseError('Database unavailable')

            cache.source.reader = fail
            stale = cache.get()
            self.assertFalse(stale['ok'])
            self.assertEqual(stale['snapshot'], first['snapshot'])
            clock.return_value = 6
            cache.source.reader = lambda names: rows
            recovered = cache.get()
            self.assertTrue(recovered['ok'])
            self.assertIsNone(recovered['error'])

    def test_tabs_share_one_database_read_within_two_seconds(self):
        calls = []
        with patch('dashboard.time.monotonic', return_value=0):
            cache = fixture_cache(reader=lambda names: calls.append(names) or [])
            for _ in range(4):
                cache.get()
        self.assertEqual(len(calls), 1)

    def test_raw_cli_errors_and_passwords_never_reach_browser_error(self):
        with patch('dashboard.subprocess.run') as run:
            run.return_value.returncode = 1
            run.return_value.stderr = 'password=secret-value SQL error'
            with self.assertRaises(dashboard.DatabaseError) as error:
                dashboard.read_database(FIXTURE_PARTY)
        self.assertNotIn('secret-value', str(error.exception))


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = fixture_cache(reader=lambda names: [character('Aster', 1), quest(1)])
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.handler(cls.cache, 0))
        cls.port = cls.server.server_port
        cls.server.RequestHandlerClass = dashboard.handler(cls.cache, cls.port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_real_http_snapshot_and_local_assets(self):
        with urlopen(self.base + '/api/snapshot') as response:
            data = json.load(response)
            self.assertTrue(data['ok'])
            self.assertEqual(data['snapshot']['views']['party']['summary']['characters'], 1)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertNotIn('Access-Control-Allow-Origin', response.headers)
        for path in ['/', '/app.js', '/style.css', '/emblem.svg']:
            with urlopen(self.base + path) as response:
                self.assertEqual(response.status, 200)

    def test_cross_origin_and_unexpected_host_are_rejected(self):
        for headers in [{'Origin': 'https://example.com'}, {'Host': 'attacker.example'},
                        {'Sec-Fetch-Site': 'cross-site'}]:
            with self.subTest(headers=headers), self.assertRaises(HTTPError) as error:
                urlopen(Request(self.base + '/api/snapshot', headers=headers))
            self.assertEqual(error.exception.code, 403)

    def test_private_files_and_path_traversal_are_not_served(self):
        for path in ['/../.playerbots.env', '/.playerbots.env', '/dashboard.py', '/api/sql']:
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(self.base + path)
            self.assertEqual(error.exception.code, 404)


from test_support import fixture_cache, PARTY as FIXTURE_PARTY

if __name__ == '__main__':
    unittest.main()
