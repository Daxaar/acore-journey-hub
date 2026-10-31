"""Public builds omit local state and new installations start without seeded game data."""
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import shutil
import time
import unittest
from unittest.mock import Mock
import zipfile

from dashboard import SnapshotCache
from groups import Groups
from package_release import ROOT,build,sources,current,manifest_for


class CleanStartupTests(unittest.TestCase):
    def test_empty_startup_never_reads_game_database_and_can_create_first_group(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'groups.json';reader=Mock(side_effect=AssertionError('Unexpected database read'))
            cache=SnapshotCache(reader=reader,groups_file=path)
            result=cache.get()
            self.assertTrue(result['ok'])
            self.assertEqual(result['snapshot']['groups'],{'selected':None,'groups':[]})
            self.assertEqual(result['snapshot']['views']['party']['characters'],[])
            self.assertEqual(cache.bots,())
            reader.assert_not_called()
            cache.update_groups({'action':'create','name':'My party','members':['Aster']})
            self.assertEqual(Groups(path).selected()['members'],['Aster'])

    def test_persisted_empty_group_configuration_is_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'groups.json';path.write_text('{"selected":null,"groups":[]}')
            self.assertIsNone(Groups(path).selected())


class PackageTests(unittest.TestCase):
    def test_watcher_rebuilds_source_changes_and_prevents_duplicate_watchers(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'initial';build(output=output)
            root=Path(folder)/'watch-app';shutil.copytree(output/'character-hub',root)
            process=subprocess.Popen([sys.executable,str(root/'package_release.py'),'--watch'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                manifest=root/'dist/character-hub/release-manifest.json'
                deadline=time.monotonic()+10
                while not manifest.exists() and time.monotonic()<deadline:time.sleep(.1)
                self.assertTrue(manifest.exists())
                original=json.loads(manifest.read_text())['source_sha256']
                duplicate=subprocess.run([sys.executable,str(root/'package_release.py'),'--watch'],timeout=5,capture_output=True)
                self.assertEqual(duplicate.returncode,0)
                asset=root/'static/emblem.svg';asset.write_bytes(asset.read_bytes()+b'\n')
                deadline=time.monotonic()+10;changed=False
                while time.monotonic()<deadline:
                    try:changed=json.loads(manifest.read_text())['source_sha256']!=original
                    except FileNotFoundError:pass
                    if changed:break
                    time.sleep(.1)
                self.assertTrue(changed)
                # Updating the builder's allowlist must reload the watcher itself.
                (root/'future_feature.py').write_text('# A new application module.\n')
                builder=root/'package_release.py'
                builder.write_text(builder.read_text().replace("'journal.py',", "'journal.py','future_feature.py',"))
                deadline=time.monotonic()+10;included=False
                while time.monotonic()<deadline:
                    try:included='future_feature.py' in json.loads(manifest.read_text())['files']
                    except FileNotFoundError:pass
                    if included:break
                    time.sleep(.1)
                self.assertTrue(included)
            finally:process.terminate();process.wait(timeout=5)

    def test_private_state_excluded_hashes_match_and_build_is_reproducible(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder);archive=build(output=output);first=archive.read_bytes()
            with zipfile.ZipFile(archive) as bundle:
                self.assertIsNone(bundle.testzip())
                names={name.removeprefix('character-hub/') for name in bundle.namelist()}
                for name in ['groups.json','watchlist.json','watch-notes.json','settings.json','network.json',
                             'client-models.json','connection.json','deployment.json','gear-planner.json','activity.sqlite3','journal.sqlite3','README.local.md','VALIDATION.md']:
                    self.assertNotIn(name,names)
                self.assertFalse(any(name.startswith(('assets/','vendor/','backups/','.run/','.qa','.git/')) for name in names))
                manifest=json.loads(bundle.read('character-hub/release-manifest.json'))
                self.assertEqual(set(manifest['files'])|{'release-manifest.json'},names)
                for name,record in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(bundle.read('character-hub/'+name)).hexdigest(),record['sha256'])
                self.assertEqual(json.loads(bundle.read('character-hub/examples/network.json')),
                                 {'listen':'127.0.0.1','allowed_hosts':[]})
                self.assertNotIn(('/home/'+'private-user').encode(),bundle.read('character-hub/README.md'))
                self.assertEqual(bundle.getinfo('character-hub/start.sh').external_attr>>16 & 0o777,0o755)
            build(output=output);self.assertEqual(first,archive.read_bytes())
            self.assertTrue(current(output,manifest_for(sources())))
            # A release tree contaminated by a local run is rebuilt cleanly.
            (output/'character-hub'/'watchlist.json').write_text('["Privatecharacter"]')
            self.assertFalse(current(output,manifest_for(sources())))
            build(output=output,if_changed=True)
            self.assertFalse((output/'character-hub'/'watchlist.json').exists())
