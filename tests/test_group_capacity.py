"""Ten-member groups persist and work across the roster-backed features."""
import tempfile
from pathlib import Path
import unittest

from groups import Groups
from armory import bag_space_sql
from professions import skills_sql
from gear_sources import snapshot_sql
from quest_log import QuestLogProvider
from dashboard import objectives
from test_dashboard import character
from test_support import fixture_cache

NAMES = ['Aster', 'Bran', 'Cora', 'Dena', 'Eryn', 'Fenn', 'Gwen', 'Hale', 'Iris', 'Jora']


class GroupCapacityTests(unittest.TestCase):
    def test_ten_members_create_edit_reload_and_compare_in_order(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'groups.json'
            groups = Groups(path)
            groups.update({'action': 'create', 'name': 'Ten adventurers', 'members': NAMES})
            selected = groups.data['selected']
            self.assertEqual(Groups(path).selected()['members'], NAMES)
            groups.update({'action': 'edit', 'id': selected, 'name': 'Reverse order', 'members': NAMES[::-1]})
            self.assertEqual(Groups(path).selected()['members'], NAMES[::-1])
            with self.assertRaises(ValueError):
                groups.update({'action': 'edit', 'id': selected, 'name': 'Too many', 'members': NAMES + ['Kora']})
            self.assertEqual(Groups(path).selected()['members'], NAMES[::-1])

        rows = [character(name, i + 1) for i, name in enumerate(NAMES)]
        cache = fixture_cache(bots=(), reader=lambda names: rows)
        cache.update_groups({'action': 'create', 'name': 'Ten adventurers', 'members': NAMES[::-1]})
        self.assertEqual([c['name'] for c in cache.get()['snapshot']['views']['party']['characters']], NAMES[::-1])

    def test_roster_queries_accept_ten_and_reject_eleven(self):
        for query in [bag_space_sql, skills_sql, lambda names: snapshot_sql(names, [])]:
            with self.subTest(query=query):
                sql = query(NAMES)
                for name in NAMES:
                    self.assertIn('0x' + name.encode().hex(), sql)
                with self.assertRaises(ValueError):
                    query(NAMES + ['Kora'])

    def test_quest_party_status_keeps_all_ten_in_group_order(self):
        calls = []
        rows = [{'kind': 'party_status', 'name': name, 'class': 1, 'level': 10,
                 'status': 1, 'rewarded': 0} for name in NAMES[::-1]]
        provider = QuestLogProvider(objectives, reader=lambda sql: calls.append(sql) or rows)
        group = {'id': 'ten', 'name': 'Ten adventurers', 'members': NAMES}
        result = provider.party_status(group, 413)
        self.assertEqual([c['name'] for c in result['characters']], NAMES)
        self.assertIn('LIMIT 10;', calls[0])
        with self.assertRaises(ValueError):
            provider.party_status({**group, 'members': NAMES + ['Kora']}, 413)
        self.assertEqual(len(calls), 1)
