import unittest
from unittest.mock import Mock, patch
from server_identity import ServerIdentity
from mysql_access import DatabaseError


class ServerIdentityTests(unittest.TestCase):
    def test_automatic_realm_hostname_and_cache(self):
        reader = Mock(return_value=[{'name': 'My Realm'}])
        with patch.dict('os.environ', {}, clear=True), patch('socket.gethostname', return_value='RealmHost'):
            identity = ServerIdentity(reader)
            self.assertEqual(identity.get(), {'realm': 'My Realm', 'host': 'RealmHost'})
            identity.get()
            reader.assert_called_once()
            self.assertIn('acore_auth.realmlist', reader.call_args.args[0])

    def test_explicit_realm_and_host(self):
        reader = Mock(return_value=[{'name': 'Chosen Realm'}])
        with patch.dict('os.environ', {'LEMMINGS_REALM_ID': '2', 'LEMMINGS_HOST_NAME': 'HubHost'}):
            self.assertEqual(ServerIdentity(reader).get()['host'], 'HubHost')
            self.assertIn('WHERE id=2', reader.call_args.args[0])

    def test_ambiguous_missing_and_offline(self):
        for rows, label in [([], 'Realm unavailable'), ([{'name': 'A'}, {'name': 'B'}], 'Multiple realms: set CHARACTER_HUB_REALM_ID')]:
            with patch.dict('os.environ', {}, clear=True):
                self.assertEqual(ServerIdentity(Mock(return_value=rows)).get()['realm'], label)
        self.assertEqual(ServerIdentity(Mock(side_effect=DatabaseError('offline'))).get()['realm'], 'Realm unavailable')

    def test_invalid_realm_id_never_queries(self):
        reader = Mock()
        with patch.dict('os.environ', {'LEMMINGS_REALM_ID': '1;DROP TABLE realmlist'}):
            self.assertEqual(ServerIdentity(reader).get()['realm'], 'Realm unavailable')
        reader.assert_not_called()
