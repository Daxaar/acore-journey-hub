"""Portable setup verifies the destination guild before creating local state."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import deployment_config
from deploy import bootstrap
from groups import Groups


class DeploymentTests(unittest.TestCase):
    def test_complete_roster_creates_group_and_rerun_preserves_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'groups.json'
            query = Mock(return_value=[{'name': 'Aster'}, {'name': 'Bran'}])
            bootstrap(path, ['Aster', 'Bran'], query)
            self.assertEqual(Groups(path).selected()['members'], ['Aster', 'Bran'])
            before = path.read_bytes()
            query.reset_mock()
            bootstrap(path, ['Other'], query)
            query.assert_not_called()
            self.assertEqual(path.read_bytes(), before)

    def test_missing_guild_or_partial_roster_stays_empty(self):
        for rows in ([], [{'name': 'Aster'}]):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'groups.json'
                bootstrap(path, ['Aster', 'Bran'], Mock(return_value=rows))
                self.assertFalse(path.exists())

    def test_connection_failure_does_not_create_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'groups.json'
            with self.assertRaises(RuntimeError):
                bootstrap(path, ['Aster'], Mock(side_effect=RuntimeError('unavailable')))
            self.assertFalse(path.exists())

    def test_saved_containers_and_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'deployment.json'
            path.write_text(json.dumps({'db_container': 'realm-db', 'world_container': 'realm-world'}))
            with patch.object(deployment_config, 'CONFIG', path), patch.dict('os.environ', {}, clear=True):
                self.assertEqual(deployment_config.container('db_container'), 'realm-db')
                with patch.dict('os.environ', {'LEMMINGS_DB_CONTAINER': 'override-db'}):
                    self.assertEqual(deployment_config.container('db_container'), 'override-db')

    def test_invalid_names_rejected_before_query(self):
        query = Mock()
        with self.assertRaises(ValueError):
            bootstrap(None, ["bad'name"], query)
        query.assert_not_called()
