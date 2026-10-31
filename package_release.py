#!/usr/bin/env python3
"""Build a reproducible, allowlisted public source package, never a copy of live state."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import sys
import zipfile

ROOT=Path(__file__).resolve().parent
NAME='character-hub'
VERSION='0.1.3'
ARCHIVE_NAME='azerothcore-character-hub-v'+VERSION
SOURCE_FILES=(
    'docs/screenshots/training.png','training.py','tests/training_browser_check.py','item_tooltips.py','spell_tooltips.py','prepare_tooltip_assets.py','QUICKSTART.md','connection.py','VERSION','CHANGELOG.md','AUDIT.md','DEPLOYMENT.md','RELEASE_VALIDATION.md','docs/screenshots/overview.png','docs/screenshots/journal.png','docs/screenshots/armory.png','docs/screenshots/planner.png','LICENSE-PROPOSAL.md','examples/connection.env','tests/test_portable_config.py',
    'tests/professions_tooltip_browser_check.py','tests/inventory_browser_check.py',
    'gear_planner.py','gear_sources.py','gear_eligibility.py','prepare_gear_assets.py',
    'activity_history.py','auctions.py','armory.py','client_models.py','dashboard.py','data_sources.py',
    'equipment_models.py','groups.py','mysql_access.py','observed_changes.py','planning.py',
    'prepare_armory_assets.py','prepare_profession_assets.py','prepare_quest_assets.py',
    'professions.py','quest_log.py','settings.py','sql_console.py','watch_notes.py','journal.py',
    'rested_xp.py','server_identity.py','deployment_config.py','deploy.py','package_release.py','requirements.txt','preview.py','start.sh','setup.sh','enable-lan.ps1',
    'AGENTS.md','PUBLIC_README.md','.gitignore','.github/workflows/package.yml',
    'static/auction-condensed.ttf','third_party/RobotoCondensed-OFL.txt',
    'third_party/mpyq.py','third_party/MPYQ-LICENSE','third_party/README.md',
)


def digest(data):return hashlib.sha256(data).hexdigest()


def sources(root=ROOT):
    root=Path(root)
    names=list(SOURCE_FILES)
    names += [p.relative_to(root).as_posix() for p in (root/'static').glob('*')
              if p.suffix in {'.html','.css','.js','.svg'}]
    names += [p.relative_to(root).as_posix() for p in (root/'tests').glob('test_*.py')]
    if (root/'LICENSE').exists():names.append('LICENSE')
    result={}
    for name in sorted(set(names)):
        path=root/name
        if path.is_symlink() or not path.is_file():raise ValueError('Missing or symlinked release source: '+name)
        result[name]=(path.read_bytes(),0o755 if name.endswith('.sh') else 0o644)
    result['README.md']=result['PUBLIC_README.md']
    result['examples/network.json']=(b'{"listen":"127.0.0.1","allowed_hosts":[]}\n',0o644)
    result['examples/client-models.json']=(b'{"enabled":false,"client_path":""}\n',0o644)
    return result


def manifest_for(files):
    records={name:{'sha256':digest(data),'mode':mode} for name,(data,mode) in sorted(files.items())}
    fingerprint=digest(json.dumps(records,sort_keys=True,separators=(',',':')).encode())
    return {'format':1,'source_sha256':fingerprint,'files':records}


def current(output, manifest):
    tree=output/NAME;archive=output/(ARCHIVE_NAME+'.zip');checksum=output/(ARCHIVE_NAME+'.zip.sha256')
    try:
        if json.loads((tree/'release-manifest.json').read_text())!=manifest:return False
        expected=set(manifest['files'])|{'release-manifest.json'}
        if {p.relative_to(tree).as_posix() for p in tree.rglob('*') if p.is_file()}!=expected:return False
        if any((tree/name).is_symlink() or digest((tree/name).read_bytes())!=record['sha256']
               for name,record in manifest['files'].items()):return False
        return checksum.read_text().split()[0]==digest(archive.read_bytes())
    except (OSError,ValueError,IndexError):return False


def build(root=ROOT,output=None,if_changed=False):
    root=Path(root);output=Path(output) if output else root/'dist'
    files=sources(root);manifest=manifest_for(files)
    if if_changed and current(output,manifest):return output/(ARCHIVE_NAME+'.zip')
    output.mkdir(parents=True,exist_ok=True)
    # Stage all output before replacing the previous complete archive.
    with tempfile.TemporaryDirectory(prefix='.release-',dir=output) as folder:
        staging=Path(folder);tree=staging/NAME;tree.mkdir()
        files['release-manifest.json']=(json.dumps(manifest,indent=2,sort_keys=True).encode()+b'\n',0o644)
        for name,(data,mode) in files.items():
            target=tree/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(mode)
        archive=staging/(ARCHIVE_NAME+'.zip')
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as bundle:
            for name,(data,mode) in sorted(files.items()):
                entry=zipfile.ZipInfo(NAME+'/'+name,date_time=(1980,1,1,0,0,0))
                entry.create_system=3;entry.external_attr=(0o100000|mode)<<16;entry.compress_type=zipfile.ZIP_DEFLATED
                bundle.writestr(entry,data)
        checksum=staging/(ARCHIVE_NAME+'.zip.sha256')
        checksum.write_text(digest(archive.read_bytes())+'  '+archive.name+'\n')
        destination=output/NAME
        if destination.is_symlink():raise ValueError('Refusing symlinked release directory')
        if destination.exists():shutil.rmtree(destination)
        tree.rename(destination)
        os.replace(archive,output/archive.name);os.replace(checksum,output/checksum.name)
    print('Clean public package: '+str(output/(ARCHIVE_NAME+'.zip')),flush=True)
    return output/(ARCHIVE_NAME+'.zip')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--if-changed',action='store_true')
    parser.add_argument('--watch',action='store_true',help='Rebuild automatically when allowlisted source changes')
    args=parser.parse_args()
    script_hash=digest(Path(__file__).read_bytes())
    lock=None
    if args.watch:
        # One source watcher per installation, including across dashboard restarts.
        import fcntl
        run=ROOT/'.run';run.mkdir(exist_ok=True)
        lock=(run/'package-watch.lock').open('a')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        (run/'package-watch.pid').write_text(str(os.getpid())+'\n')
    try:
        while True:
            try:
                if args.watch and digest(Path(__file__).read_bytes())!=script_hash:
                    lock.close()
                    os.execv(sys.executable,[sys.executable,str(ROOT/'package_release.py'),'--watch'])
                build(if_changed=args.if_changed or args.watch)
            except (OSError,ValueError) as exc:
                if not args.watch:raise
                print('Source not ready; keeping the last package and retrying: '+str(exc),flush=True)
            if not args.watch:break
            time.sleep(3)
    except KeyboardInterrupt:pass
    finally:
        if lock:lock.close()


if __name__=='__main__':main()
