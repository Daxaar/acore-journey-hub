"""Rested pool units, server cap, offline accrual and missing-provider semantics."""
import os
import unittest
from unittest.mock import patch
from rested_xp import rested_view
from mysql_access import snapshot_sql


@patch.dict(os.environ, {}, clear=True)
class RestedTests(unittest.TestCase):
    def row(self, **values):
        return dict(level=11, online=1, rest_bonus=4000, next_level_xp=10000,
                    logout_time=1000, rest_observed_at=1000, is_logout_resting=1, **values)

    def test_saved_pool_is_half_client_coverage(self):
        r = rested_view(self.row())
        self.assertEqual((r['bonus_xp'], r['coverage_xp'], r['level_percent']), (4000, 8000, 80))
        self.assertAlmostEqual(r['cap_full_percent'], 4000 / 7500 * 100)
        self.assertEqual(r['remaining_percent'], 70)
        self.assertFalse(r['estimated'])

    def test_offline_rest_and_cap(self):
        c = self.row(); c.update(online=0, rest_bonus=0, rest_observed_at=1000+8*3600)
        r = rested_view(c)
        self.assertEqual(r['level_percent'], 5)
        self.assertTrue(r['estimated'])
        c['is_logout_resting'] = 0
        self.assertAlmostEqual(rested_view(c)['level_percent'], 1.24)
        c['rest_observed_at'] += 100*86400
        self.assertEqual(rested_view(c)['level_percent'], 150)
        self.assertEqual(rested_view(c)['cap_full_percent'], 100)

    def test_custom_rates_and_max_level(self):
        with patch.dict(os.environ, {'LEMMINGS_REST_MAX_BONUS':'3', 'LEMMINGS_MAX_PLAYER_LEVEL':'60'}):
            c = self.row(); c['rest_bonus'] = 999999
            self.assertEqual(rested_view(c)['level_percent'], 300)
            c['level'] = 60
            self.assertEqual(rested_view(c)['state'], 'max_level')

    def test_missing_and_invalid_values_are_unavailable(self):
        for key, value in [('rest_bonus', None), ('next_level_xp', 0), ('rest_bonus', float('nan'))]:
            c = self.row(); c[key] = value
            self.assertEqual(rested_view(c)['state'], 'unavailable')
        c = self.row(); c.update(online=0, logout_time=0)
        self.assertEqual(rested_view(c)['state'], 'unavailable')

    def test_snapshot_fetches_required_fields(self):
        sql = snapshot_sql(('Aster',))
        for field in ('c.rest_bonus', 'c.is_logout_resting', 'px.Experience', 'UNIX_TIMESTAMP()', 'px.Level=c.level'):
            self.assertIn(field, sql)
