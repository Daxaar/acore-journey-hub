"""Hub-only backup/update/restore, WAL snapshots, rollback and archive boundaries."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import warnings
from unittest.mock import patch
from urllib.request import urlopen
import zipfile

import hub_runtime
import update
from package_release import manifest_for

SERVER='''from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import argparse,os
p=argparse.ArgumentParser();p.add_argument('--port',type=int);p.add_argument('--listen',default='127.0.0.1');a=p.parse_args()
class H(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  data=(Path(__file__).parent/'static/professions.js').read_bytes() if self.path=='/professions.js' else os.environ.get('JOURNEY_HUB_HOST_NAME','missing').encode()
  self.send_response(200);self.end_headers();self.wfile.write(data)
HTTPServer((a.listen,a.port),H).serve_forever()
'''


def app(root,version='1.0',server=False):
    root.mkdir(exist_ok=True)
    files={'dashboard.py':SERVER if server else '# '+version+'\n','setup.sh':'#!/bin/bash\nexit 0\n',
           'start.sh':'#!/bin/bash\nexec "'+sys.executable+'" "$(dirname "$0")/dashboard.py" "$@"\n',
           'requirements.txt':'','VERSION':version+'\n','static/professions.js':'// '+version+'\n'}
    records={}
    for name,text in files.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        mode=0o755 if name.endswith('.sh') else 0o644;path.chmod(mode)
        records[name]=(path.read_bytes(),mode)
    manifest=manifest_for(records)
    (root/'release-manifest.json').write_text(json.dumps(manifest))
    return root


def archive(source,destination,folder='acore-journey-hub',extra=None):
    with zipfile.ZipFile(destination,'w') as z:
        for path in source.rglob('*'):
            if path.is_file():z.write(path,folder+'/'+path.relative_to(source).as_posix())
        if extra:z.writestr(*extra)
    Path(str(destination)+'.sha256').write_text(hashlib.sha256(destination.read_bytes()).hexdigest()+'  '+destination.name+'\n')
    return destination


class MaintenanceTests(unittest.TestCase):
    def test_full_backup_preserves_files_symlinks_and_online_wal_databases(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=app(base/'installed')
            (root/'connection.json').write_text('{"private":"keep"}')
            (root/'watch-notes.json').write_text('{"Aster":"Note with image data"}')
            (root/'assets').mkdir();(root/'assets/cache.bin').write_bytes(b'cached model')
            external=base/'game-files';external.mkdir();(external/'worldserver.conf').write_text('never change')
            (root/'client-link').symlink_to(external,target_is_directory=True)
            (root/'.venv/bin').mkdir(parents=True);(root/'.venv/bin/python').symlink_to(sys.executable)
            for skip in ('backups','dist','.run','.git','.codex'):
                (root/skip).mkdir();(root/skip/'ignored').write_text('not recursive')
            # A development checkout is deliberately not an update target.
            (root/'.git/ignored').unlink();(root/'.git').rmdir()
            with ExitStack() as stack:
                for name in ('activity.sqlite3','journal.sqlite3','assets/extra.db'):
                    db=stack.enter_context(sqlite3.connect(root/name));db.execute('PRAGMA journal_mode=WAL')
                    db.execute('CREATE TABLE saved(value BLOB)');db.execute('INSERT INTO saved VALUES (?)',(b'story and screenshot',));db.commit()
                snapshot=update.backup(root)
            metadata=update.validate_backup(snapshot,root)
            self.assertEqual(sum(v['kind']=='sqlite' for v in metadata['files'].values()),3)
            self.assertTrue((snapshot/'files/.venv/bin/python').is_symlink())
            self.assertTrue((snapshot/'files/client-link').is_symlink())
            self.assertFalse((snapshot/'files/client-link').is_dir() and not (snapshot/'files/client-link').is_symlink())
            self.assertFalse(any(name.endswith(('-wal','-shm')) for name in metadata['files']))
            self.assertFalse(any(name.startswith(('backups/','dist/','.run/','.codex/')) for name in metadata['files']))
            for name in ('activity.sqlite3','journal.sqlite3','assets/extra.db'):
                with sqlite3.connect(snapshot/'files'/name) as copied:self.assertEqual(copied.execute('SELECT value FROM saved').fetchone()[0],b'story and screenshot')
            self.assertEqual((snapshot/'files/connection.json').read_bytes(),(root/'connection.json').read_bytes())
            self.assertEqual(snapshot.stat().st_mode & 0o777,0o700)
            self.assertEqual((external/'worldserver.conf').read_text(),'never change')

    def test_update_preserves_state_and_restore_reverts_full_files_and_databases(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=app(base/'installed');new=app(base/'new','2.0')
            (root/'groups.json').write_text('original groups');(root/'network.json').write_text('{}')
            with sqlite3.connect(root/'journal.sqlite3') as db:db.execute('CREATE TABLE story(text)');db.execute("INSERT INTO story VALUES ('before')")
            called=[]
            snapshot=update.update_install(root,new,lambda target:called.append(target))
            self.assertEqual(called,[root]);self.assertEqual((root/'VERSION').read_text(),'2.0\n')
            self.assertEqual((root/'groups.json').read_text(),'original groups')
            (root/'groups.json').write_text('later groups');(root/'new-local-file').write_text('saved before restoring')
            with sqlite3.connect(root/'journal.sqlite3') as db:db.execute("UPDATE story SET text='later'")
            rescue=update.restore_install(root,snapshot)
            self.assertEqual((root/'VERSION').read_text(),'1.0\n')
            self.assertEqual((root/'groups.json').read_text(),'original groups')
            self.assertFalse((root/'new-local-file').exists())
            self.assertEqual((rescue/'files/new-local-file').read_text(),'saved before restoring')
            with sqlite3.connect(root/'journal.sqlite3') as db:self.assertEqual(db.execute('SELECT text FROM story').fetchone()[0],'before')
            self.assertEqual(update.latest_backup(root),snapshot)

    def test_dependency_failure_rolls_back_code_settings_venv_and_local_databases(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=app(base/'installed');new=app(base/'new','2.0')
            (root/'settings.json').write_text('keep');(root/'.venv').mkdir();(root/'.venv/dependency').write_text('old')
            with sqlite3.connect(root/'activity.sqlite3') as db:db.execute('CREATE TABLE history(value)');db.execute('INSERT INTO history VALUES (1)')
            def fail(target):
                (target/'settings.json').write_text('changed');(target/'.venv/dependency').write_text('new')
                (target/'unexpected').write_text('remove after rollback')
                with sqlite3.connect(target/'activity.sqlite3') as db:db.execute('UPDATE history SET value=2')
                raise RuntimeError('synthetic installation failure')
            with self.assertRaisesRegex(RuntimeError,'previous Hub files'):
                update.update_install(root,new,fail)
            self.assertEqual((root/'VERSION').read_text(),'1.0\n');self.assertEqual((root/'settings.json').read_text(),'keep')
            self.assertEqual((root/'.venv/dependency').read_text(),'old');self.assertFalse((root/'unexpected').exists())
            with sqlite3.connect(root/'activity.sqlite3') as db:self.assertEqual(db.execute('SELECT value FROM history').fetchone()[0],1)
            self.assertFalse((root/'.run/update-state.json').exists())

    def test_restore_to_pre_updater_release_keeps_recovery_commands_available(self):
        with tempfile.TemporaryDirectory() as folder:
            root=app(Path(folder)/'installed');snapshot=update.backup(root)
            for name,content in update.RECOVERY_TOOLS.items():(root/name).write_bytes(content)
            update.restore_install(root,snapshot)
            self.assertEqual((root/'update.py').read_bytes(),update.RECOVERY_TOOLS['update.py'])
            self.assertTrue((root/'hub_runtime.py').is_file())

    def test_corrupt_snapshot_is_rejected_before_touching_current_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=app(Path(folder)/'installed');snapshot=update.backup(root)
            (snapshot/'files/dashboard.py').write_text('tampered')
            with self.assertRaises(ValueError):update.restore_install(root,snapshot)
            self.assertEqual((root/'dashboard.py').read_text(),'# 1.0\n')

    def test_restore_can_recover_a_corrupted_current_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root=app(Path(folder)/'installed')
            with sqlite3.connect(root/'journal.sqlite3') as db:db.execute('CREATE TABLE story(value)');db.execute('INSERT INTO story VALUES (7)')
            snapshot=update.backup(root)
            (root/'journal.sqlite3').write_bytes(b'corrupted database bytes')
            rescue=update.restore_install(root,snapshot)
            self.assertEqual((rescue/'files/journal.sqlite3').read_bytes(),b'corrupted database bytes')
            with sqlite3.connect(root/'journal.sqlite3') as db:self.assertEqual(db.execute('SELECT value FROM story').fetchone()[0],7)

    def test_interrupted_update_record_is_recoverable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=app(Path(folder)/'installed');snapshot=update.backup(root,'before-update')
            (root/'dashboard.py').unlink()
            update.json_file(root/'.run/update-state.json',{'backup':str(snapshot),'service':None})
            update.restore_install(root)
            self.assertTrue((root/'dashboard.py').is_file());self.assertFalse((root/'.run/update-state.json').exists())

    def test_bad_zip_checksum_traversal_symlinks_and_private_state_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);source=app(base/'source','2.0')
            zipped=archive(source,base/'good.zip')
            extracted=update.unpack(zipped,base/'good');self.assertEqual(extracted.name,'acore-journey-hub')
            Path(str(zipped)+'.sha256').write_text('0'*64)
            with self.assertRaises(ValueError):update.unpack(zipped,base/'bad-checksum')
            for index,extra in enumerate([('../escape',b'bad'),('acore-journey-hub/../escape',b'bad')]):
                zipped=archive(source,base/f'traversal{index}.zip',extra=extra)
                with self.assertRaises(ValueError):update.unpack(zipped,base/f'unsafe{index}')
            self.assertFalse((base/'escape').exists())
            private=source/'network.json';private.write_text('{"listen":"0.0.0.0"}')
            manifest=json.loads((source/'release-manifest.json').read_text())
            records={name:((source/name).read_bytes(),record['mode']) for name,record in manifest['files'].items()}
            records['network.json']=(private.read_bytes(),0o644)
            (source/'release-manifest.json').write_text(json.dumps(manifest_for(records)))
            with self.assertRaises(ValueError):update.unpack(archive(source,base/'state.zip'),base/'state')

    def test_legacy_release_root_is_accepted_without_renaming_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);source=app(base/'source','2.0')
            extracted=update.unpack(archive(source,base/'legacy.zip','character-hub'),base/'stage')
            self.assertEqual(extracted.name,'character-hub')

    def test_dependency_step_is_only_hub_setup_without_asset_generation(self):
        with tempfile.TemporaryDirectory() as folder,patch('update.subprocess.run') as run:
            root=Path(folder);update.dependencies(root)
            run.assert_called_once_with(['bash',str(root/'setup.sh'),'--skip-assets'],cwd=root,check=True)

    def test_process_identity_rejects_unrelated_python_and_other_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=app(base/'installed');other=app(base/'other')
            script=other/'package_release.py';script.write_text('import time;time.sleep(60)')
            child=subprocess.Popen([sys.executable,str(script),'--watch'])
            try:
                time.sleep(.1)
                self.assertIsNone(hub_runtime.process(child.pid,root))
                update.stop(root,[{'pid':child.pid,'ticks':'fake','kind':'watcher'}])
                self.assertIsNone(child.poll())
            finally:child.terminate();child.wait(timeout=5)

    def test_running_hub_is_restarted_on_same_port_and_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=app(base/'installed',server=True);new=app(base/'new','2.0',server=True)
            with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
            environment=os.environ.copy();environment['JOURNEY_HUB_HOST_NAME']='Preserved host'
            child=subprocess.Popen([sys.executable,str(root/'dashboard.py'),'--port',str(port)],cwd=root,env=environment)
            try:
                for _ in range(50):
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/env',timeout=.1) as response:self.assertEqual(response.read(),b'Preserved host')
                        break
                    except OSError:time.sleep(.05)
                snapshot=update.update_install(root,new,lambda target:None)
                child.wait(timeout=5)
                with urlopen(f'http://127.0.0.1:{port}/professions.js',timeout=2) as response:self.assertEqual(response.read(),b'// 2.0\n')
                with urlopen(f'http://127.0.0.1:{port}/env',timeout=2) as response:self.assertEqual(response.read(),b'Preserved host')
                update.restore_install(root,snapshot)
                with urlopen(f'http://127.0.0.1:{port}/professions.js',timeout=2) as response:self.assertEqual(response.read(),b'// 1.0\n')
            finally:
                hub_runtime.stop(root,hub_runtime.processes(root))
                if child.poll() is None:child.terminate();child.wait(timeout=5)

    def test_one_command_download_update_and_foreign_backup_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=app(base/'installed');source=app(base/'release','2.0')
            zipped=archive(source,base/'release.zip')
            with patch.object(update,'ROOT',root), patch('sys.argv',['update.py']), patch('update.latest_release',return_value=zipped) as download:
                update.main()
            download.assert_called_once();self.assertEqual((root/'VERSION').read_text(),'2.0\n')
            other=app(base/'other');foreign=update.backup(other)
            with patch('update.stop') as stop:
                with self.assertRaises(ValueError):update.restore_install(root,foreign)
                stop.assert_not_called()

    def test_release_symlinks_duplicates_and_oversized_archives_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);source=app(base/'release','2.0')
            info=zipfile.ZipInfo('acore-journey-hub/link');info.create_system=3;info.external_attr=0o120777<<16
            zipped=archive(source,base/'link.zip',extra=(info,'/outside/file'))
            with self.assertRaises(ValueError):update.unpack(zipped,base/'link-stage')
            with patch.object(update,'MAX_EXPANDED',1):
                with self.assertRaises(ValueError):update.unpack(archive(source,base/'large.zip'),base/'large-stage')
            with self.assertWarns(UserWarning):
                duplicate=archive(source,base/'duplicate.zip',extra=('acore-journey-hub/VERSION','another version'))
            with self.assertRaises(ValueError):update.unpack(duplicate,base/'duplicate-stage')

    def test_update_never_writes_through_a_link_to_external_files(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=app(base/'installed');source=app(base/'new','2.0');external=base/'game-files'
            (root/'static').rename(external);(root/'static').symlink_to(external,target_is_directory=True)
            before=(external/'professions.js').read_bytes()
            with self.assertRaises(RuntimeError):update.update_install(root,source,lambda target:None)
            self.assertEqual((external/'professions.js').read_bytes(),before)
            self.assertTrue((root/'static').is_symlink());self.assertEqual((root/'VERSION').read_text(),'1.0\n')

    def test_maintenance_lock_prevents_concurrent_operations(self):
        with tempfile.TemporaryDirectory() as folder:
            root=app(Path(folder)/'installed')
            with update.maintenance(root):
                with self.assertRaises(ValueError):
                    with update.maintenance(root):pass

    def test_private_release_download_uses_only_github_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            name='azerothcore-journey-hub-v2.0.zip'
            info={'assets':[{'name':name},{'name':name+'.sha256'}]}
            with patch('update.shutil.which',return_value='/fake/gh'),patch('update.subprocess.run',side_effect=[subprocess.CompletedProcess([],0,json.dumps(info)),subprocess.CompletedProcess([],0)]) as run:
                self.assertEqual(update.latest_release(folder),Path(folder)/name)
            self.assertEqual(run.call_args_list[0].args[0][:3],['gh','release','view'])
            self.assertEqual(run.call_args_list[1].args[0][:3],['gh','release','download'])

    def test_latest_backup_uses_creation_time_and_same_release_can_repair_files(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=app(base/'installed');source=app(base/'same')
            first=update.backup(root);second=update.backup(root)
            self.assertEqual(update.latest_backup(root),second)
            (root/'dashboard.py').write_text('broken local file')
            snapshot=update.update_install(root,source,lambda target:None)
            self.assertIsNotNone(snapshot)
            self.assertEqual((root/'dashboard.py').read_text(),'# 1.0\n')
            self.assertEqual((snapshot/'files/dashboard.py').read_text(),'broken local file')

    def test_game_server_directory_is_refused_even_if_hub_files_are_present(self):
        with tempfile.TemporaryDirectory() as folder:
            root=app(Path(folder)/'server');marker=root/'worldserver.conf';marker.write_text('never change')
            before=marker.read_bytes()
            with self.assertRaisesRegex(ValueError,'game-server directory'):update.backup(root)
            self.assertEqual(marker.read_bytes(),before);self.assertFalse((root/'backups').exists())

    def test_development_checkout_is_not_an_update_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root=app(Path(folder)/'installed');(root/'.git').mkdir()
            with self.assertRaisesRegex(ValueError,'development Git checkout'):update.validate_install(root)
