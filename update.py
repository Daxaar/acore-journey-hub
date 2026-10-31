#!/usr/bin/env python3
"""Back up, update or restore only Journey Hub files and local SQLite databases."""
import argparse
from contextlib import contextmanager, closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen
import uuid
import zipfile

from hub_runtime import processes, stop, restart

ROOT=Path(__file__).resolve().parent
REPOSITORY='Daxaar/acore-journey-hub'
PACKAGE_FOLDERS={'acore-journey-hub','character-hub'}
EXCLUDED={'backups','dist','.run','.git','__pycache__','.pytest_cache','.cache','.codex','.agents','.aws'}
PRIVATE={'connection.json','deployment.json','groups.json','watchlist.json','watch-notes.json',
         'settings.json','network.json','client-models.json','gear-planner.json'}
MAX_ARCHIVE=128*1024*1024
MAX_EXPANDED=512*1024*1024
# Keep the verified running updater available after rolling back a pre-updater release.
RECOVERY_TOOLS={name:(ROOT/name).read_bytes() for name in ('update.py','hub_runtime.py')}


def digest(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def relative(name):
    if not isinstance(name,str) or not name or '\\' in name or '\0' in name:
        raise ValueError('Invalid file path in manifest.')
    path=PurePosixPath(name)
    if path.is_absolute() or any(part in ('','.','..') for part in name.split('/')):
        raise ValueError('Unsafe file path in manifest.')
    return path


def excluded(path):
    return any(part in EXCLUDED for part in path.parts) or path.name.endswith('.pyc')


def entries(root):
    """Never traverse symlinks, including externally stored client/game assets."""
    root=Path(root)
    def walk(directory):
        for path in sorted(directory.iterdir()):
            name=path.relative_to(root)
            if excluded(name):continue
            yield path,name
            if path.is_dir() and not path.is_symlink():yield from walk(path)
    yield from walk(root)


def sqlite_file(path):
    if path.suffix in ('.sqlite3','.sqlite'):return True
    with path.open('rb') as source:return source.read(16)==b'SQLite format 3\x00'


def json_file(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.maintenance-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:
            json.dump(value,out,indent=2,sort_keys=True);out.write('\n')
            out.flush();os.fsync(out.fileno())
        os.replace(temporary,path)
    finally:Path(temporary).unlink(missing_ok=True)


def validate_install(root):
    root=Path(root).expanduser().resolve()
    # A Hub directory must be separate from a game-server installation.
    markers=('worldserver','authserver','worldserver.conf','authserver.conf','acore.sh',
             'bin/worldserver','bin/authserver','etc/worldserver.conf','env/dist/bin/worldserver')
    if any((root/name).exists() for name in markers):
        raise ValueError('This looks like an AzerothCore game-server directory. Maintenance only accepts a separate Hub installation.')
    known=all((root/name).is_file() for name in ('dashboard.py','start.sh','setup.sh','VERSION'))
    if not known:
        for manifest in (root/'backups').glob('*/backup.json'):
            try:
                data=json.loads(manifest.read_text())
                if data.get('format')==1 and data.get('install')==str(root) and {'dashboard.py','start.sh'}<=set(data.get('files',{})):
                    known=True;break
            except (OSError,ValueError,TypeError):continue
    if not known:raise ValueError('Choose an existing Hub installation with --install.')
    if (root/'.git').exists():raise ValueError('Use an installed Hub copy, not the development Git checkout.')
    return root


@contextmanager
def maintenance(root):
    run=root/'.run'
    if run.is_symlink():raise ValueError('The Hub runtime directory must not be a symlink.')
    run.mkdir(exist_ok=True)
    if (run/'maintenance.lock').is_symlink():raise ValueError('The maintenance lock must not be a symlink.')
    with (run/'maintenance.lock').open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another update, backup or restore is already running.') from None
        yield


def backup(root,kind='manual',service=None,allow_damaged=False):
    """Complete private snapshot, with online backups of every detected SQLite file."""
    root=validate_install(root)
    home=root/'backups'
    if home.is_symlink():raise ValueError('The backups directory must not be a symlink.')
    home.mkdir(mode=0o700,exist_ok=True);home.chmod(0o700)
    label=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'-'+kind
    stage=Path(tempfile.mkdtemp(prefix='.incomplete-',dir=home));files=stage/'files';files.mkdir()
    records={}
    try:
        listed=list(entries(root))
        databases={name.as_posix() for path,name in listed if path.is_file() and not path.is_symlink() and sqlite_file(path)}
        for source,name in listed:
            key=name.as_posix()
            if any(key==database+suffix for database in databases for suffix in ('-wal','-shm','-journal')):continue
            target=files/name;mode=stat.S_IMODE(source.lstat().st_mode)
            if source.is_symlink():
                link=os.readlink(source);target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(link)
                records[key]={'kind':'symlink','target':link}
            elif source.is_dir():
                target.mkdir(exist_ok=True)
                records[key]={'kind':'directory','mode':mode}
            elif source.is_file():
                target.parent.mkdir(parents=True,exist_ok=True)
                database=key in databases
                if database:
                    try:
                        with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as original, closing(sqlite3.connect(target)) as copied:
                            deadline=time.monotonic()+120
                            def progress(status,remaining,total):
                                if time.monotonic()>deadline:raise TimeoutError('SQLite backup timed out: '+key)
                            original.backup(copied,pages=256,progress=progress,sleep=.05)
                            copied.execute('PRAGMA journal_mode=DELETE')
                            if copied.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise ValueError('SQLite verification failed: '+key)
                        target.chmod(mode)
                    except (sqlite3.Error,ValueError):
                        if not allow_damaged:raise
                        target.unlink(missing_ok=True);shutil.copy2(source,target);database=False
                        print('Preserved damaged SQLite bytes before restore: '+key,flush=True)
                else:shutil.copy2(source,target)
                records[key]={'kind':'sqlite' if database else 'file','mode':mode,'sha256':digest(target)}
            else:raise ValueError('Cannot back up a special file: '+key)
        for name,record in sorted(records.items(),key=lambda item:len(PurePosixPath(item[0]).parts),reverse=True):
            if record['kind']=='directory':(files/name).chmod(record['mode'])
        metadata={'format':1,'install':str(root),'kind':kind,'created_at':datetime.now(timezone.utc).isoformat(),
                  'version':(root/'VERSION').read_text().strip() if (root/'VERSION').exists() else None,
                  'service':service,'files':records}
        json_file(stage/'backup.json',metadata)
        validate_backup(stage,root)
        final=home/label;stage.rename(final)
        print('Backup: '+str(final),flush=True)
        return final
    except BaseException:
        shutil.rmtree(stage,ignore_errors=True)
        raise


def validate_backup(folder,root):
    folder=Path(folder).resolve()
    if (folder/'backup.json').is_symlink() or (folder/'files').is_symlink():raise ValueError('Backup metadata must not be a symlink.')
    data=json.loads((folder/'backup.json').read_text())
    if data.get('format')!=1 or data.get('install')!=str(Path(root).resolve()) or not isinstance(data.get('files'),dict):
        raise ValueError('Choose a complete backup from this Hub installation.')
    base=folder/'files'
    actual={name.as_posix() for _,name in entries(base)}
    if actual!=set(data['files']):raise ValueError('Backup file list does not match its manifest.')
    for name,record in data['files'].items():
        path=base/relative(name)
        for parent in path.parents:
            if parent==base:break
            if parent.is_symlink():raise ValueError('Unsafe symlink parent in backup.')
        kind=record.get('kind')
        if kind=='symlink':
            if not path.is_symlink() or os.readlink(path)!=record['target']:raise ValueError('Backup symlink verification failed.')
        elif path.is_symlink():raise ValueError('Unexpected symlink in backup.')
        elif kind=='directory':
            if not path.is_dir():raise ValueError('Backup directory missing.')
        elif kind in ('file','sqlite'):
            if not path.is_file() or digest(path)!=record['sha256']:raise ValueError('Backup checksum verification failed: '+name)
            if kind=='sqlite':
                with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
                    if db.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise ValueError('Backup SQLite verification failed.')
        else:raise ValueError('Unknown backup record.')
    return data


def restore_files(folder,root):
    data=validate_backup(folder,root)
    location=Path(folder).resolve()
    if root in location.parents and root/'backups' not in location.parents:
        raise ValueError('Keep restore snapshots in the backups directory or outside the installation.')
    recovery=RECOVERY_TOOLS if (root/'update.py').is_file() and 'update.py' not in data['files'] else {}
    # Remove only installation content; backup history and runtime locks are retained.
    for path in root.iterdir():
        if excluded(path.relative_to(root)):continue
        if path.is_symlink() or path.is_file():path.unlink()
        elif path.is_dir():shutil.rmtree(path)
        else:raise ValueError('Unexpected special file in installation.')
    for name,record in sorted(data['files'].items(),key=lambda item:len(PurePosixPath(item[0]).parts)):
        source=Path(folder)/'files'/name;target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
        if record['kind']=='symlink':target.symlink_to(record['target'])
        elif record['kind']=='directory':target.mkdir(exist_ok=True)
        else:shutil.copy2(source,target);target.chmod(record['mode'])
    for name,record in sorted(data['files'].items(),key=lambda item:len(PurePosixPath(item[0]).parts),reverse=True):
        if record['kind']=='directory':(root/name).chmod(record['mode'])
    for name,content in recovery.items():
        (root/name).write_bytes(content);(root/name).chmod(0o644)
    return data


def latest_backup(root):
    candidates=[]
    for folder in (root/'backups').glob('*'):
        if folder.name.startswith('.') or not (folder/'backup.json').is_file():continue
        data=json.loads((folder/'backup.json').read_text())
        if data.get('kind') in ('manual','before-update') and data.get('install')==str(root):candidates.append((data['created_at'],folder))
    if not candidates:raise ValueError('No update/manual backup exists for this installation.')
    return sorted(candidates)[-1][1]


def protect_release(name):
    path=relative(name)
    if excluded(path) or path.parts[0] in PRIVATE|{'assets','.venv'} or path.parts[0].startswith('.env') or path.suffix=='.db' or any('.sqlite' in part for part in path.parts):
        raise ValueError('A release must not contain local state: '+name)
    return path


def verify_release(folder):
    folder=Path(folder)
    if (folder/'release-manifest.json').is_symlink():raise ValueError('Release manifest must not be a symlink.')
    manifest=json.loads((folder/'release-manifest.json').read_text())
    records=manifest.get('files')
    if manifest.get('format')!=1 or not isinstance(records,dict):raise ValueError('Invalid release manifest.')
    expected=set(records)|{'release-manifest.json'}
    actual={p.relative_to(folder).as_posix() for p in folder.rglob('*')
            if (p.is_file() or p.is_symlink()) and '__pycache__' not in p.relative_to(folder).parts and p.suffix!='.pyc'}
    if actual!=expected:raise ValueError('Release files do not match the manifest.')
    for name,record in records.items():
        path=folder/protect_release(name)
        if set(record)!={'sha256','mode'} or record['mode'] not in (0o644,0o755):raise ValueError('Invalid release file record.')
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent!=folder and folder in parent.parents):
            raise ValueError('Release symlinks are not supported.')
        with path.open('rb') as content:
            if content.read(16)==b'SQLite format 3\x00':raise ValueError('A release must not contain SQLite databases.')
        if digest(path)!=record['sha256']:raise ValueError('Release checksum verification failed: '+name)
    fingerprint=hashlib.sha256(json.dumps(records,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if manifest.get('source_sha256')!=fingerprint:raise ValueError('Release manifest fingerprint does not match.')
    if not {'dashboard.py','setup.sh','start.sh','requirements.txt'}<=set(records):raise ValueError('The archive is not a complete Hub release.')
    return manifest


def unpack(archive,destination,checksum=None):
    archive=Path(archive).expanduser().resolve()
    checksum=Path(checksum) if checksum else Path(str(archive)+'.sha256')
    parts=checksum.read_text().split()
    if not parts:raise ValueError('The ZIP checksum file is empty.')
    expected=parts[0]
    if not re.fullmatch('[a-fA-F0-9]{64}',expected) or digest(archive)!=expected.lower():raise ValueError('ZIP checksum verification failed.')
    if archive.stat().st_size>MAX_ARCHIVE:raise ValueError('The release ZIP is too large.')
    with zipfile.ZipFile(archive) as bundle:
        names=set();roots=set();size=0
        if len(bundle.infolist())>10000:raise ValueError('Too many release files.')
        for item in bundle.infolist():
            clean=item.filename.rstrip('/');path=relative(clean)
            if clean in names:raise ValueError('Duplicate release ZIP entry.')
            names.add(clean);roots.add(path.parts[0]);size+=item.file_size
            mode=(item.external_attr>>16)&0o170000
            if mode not in (0,stat.S_IFREG,stat.S_IFDIR):raise ValueError('Release ZIP contains a special file.')
        if size>MAX_EXPANDED or len(roots)!=1 or not roots<=PACKAGE_FOLDERS:raise ValueError('Unexpected release ZIP layout.')
        bundle.extractall(destination)
    folder=Path(destination)/next(iter(roots))
    verify_release(folder)
    return folder


def download(url,target):
    request=Request(url,headers={'User-Agent':'JourneyHub-Updater','Accept':'application/vnd.github+json'})
    with urlopen(request,timeout=30) as source, Path(target).open('wb') as out:
        total=0
        while block:=source.read(1024*1024):
            total+=len(block)
            if total>MAX_ARCHIVE:raise ValueError('Release download is too large.')
            out.write(block)


def latest_release(destination):
    destination=Path(destination)
    # gh supports authenticated private repositories; public installs need only Python.
    if shutil.which('gh'):
        result=subprocess.run(['gh','release','view','--repo',REPOSITORY,'--json','assets'],capture_output=True,text=True)
        if result.returncode==0:
            info=json.loads(result.stdout)
            candidates=[item['name'] for item in info['assets'] if item['name'].startswith('azerothcore-journey-hub-v') and item['name'].endswith('.zip')]
            if len(candidates)!=1:raise ValueError('Latest release has no unique deployment ZIP.')
            name=candidates[0]
            subprocess.run(['gh','release','download','--repo',REPOSITORY,'--dir',str(destination),'-p',name,'-p',name+'.sha256'],check=True)
            return destination/name
    try:
        with urlopen(Request('https://api.github.com/repos/'+REPOSITORY+'/releases/latest',headers={'User-Agent':'JourneyHub-Updater'}),timeout=30) as response:
            info=json.load(response)
    except OSError:
        raise ValueError('Cannot read the latest GitHub release. Check network access; for a private repository use gh auth login, or provide --archive ZIP.') from None
    assets={item['name']:item['browser_download_url'] for item in info['assets']}
    names=[name for name in assets if name.startswith('azerothcore-journey-hub-v') and name.endswith('.zip')]
    if len(names)!=1 or names[0]+'.sha256' not in assets:raise ValueError('Latest release is missing its deployment ZIP or checksum.')
    for name in (names[0],names[0]+'.sha256'):download(assets[name],destination/name)
    return destination/names[0]


def linked_target(root,target):
    return target.is_symlink() or any(parent.is_symlink() for parent in target.parents if parent!=root and root in parent.parents)


def apply_release(source,root,manifest):
    for name in [*manifest['files'],'release-manifest.json']:
        target=root/name
        if linked_target(root,target):
            raise ValueError('Refusing to replace a release path through a symlink: '+name)
        target.parent.mkdir(parents=True,exist_ok=True)
        fd,temporary=tempfile.mkstemp(prefix='.update-',dir=target.parent);os.close(fd)
        try:
            shutil.copy2(Path(source)/name,temporary)
            Path(temporary).chmod(manifest['files'].get(name,{'mode':0o644})['mode'])
            os.replace(temporary,target)
        finally:Path(temporary).unlink(missing_ok=True)


def dependencies(root):
    # Never run deploy.py or metadata generation: no game-server operation is needed.
    venv=root/'.venv'
    if venv.is_symlink():venv.unlink()
    elif venv.exists():shutil.rmtree(venv)
    subprocess.run(['bash',str(root/'setup.sh'),'--skip-assets'],cwd=root,check=True)


def update_install(root,source,install_dependencies=dependencies):
    root=validate_install(root);manifest=verify_release(source)
    state=root/'.run/update-state.json'
    if state.exists():raise ValueError('An interrupted update exists. Run python3 update.py restore first.')
    version=root/'VERSION';incoming=Path(source)/'VERSION'
    if version.exists() and incoming.exists():
        old=version.read_text().strip();new=incoming.read_text().strip()
        if re.fullmatch(r'\d+(?:\.\d+)+',old) and re.fullmatch(r'\d+(?:\.\d+)+',new) and tuple(map(int,new.split('.')))<tuple(map(int,old.split('.'))):
            raise ValueError('The release is older than this installation. Use restore for rollback.')
    installed=root/'release-manifest.json'
    matches=all(not linked_target(root,root/name) and (root/name).is_file() and digest(root/name)==record['sha256']
                for name,record in manifest['files'].items())
    if installed.exists() and matches and json.loads(installed.read_text()).get('source_sha256')==manifest['source_sha256']:
        print('This release is already installed.');return None
    active=processes(root);service=next((item for item in active if item['kind']=='server'),None)
    stop(root,active)
    snapshot=None
    try:
        snapshot=backup(root,'before-update',service)
        json_file(state,{'backup':str(snapshot),'service':service})
        apply_release(source,root,manifest)
        install_dependencies(root)
        restart(root,service)
        state.unlink(missing_ok=True)
        print('Update complete. '+('The Hub is running.' if service else 'The Hub was stopped and remains stopped.'))
        return snapshot
    except BaseException as error:
        if snapshot:
            try:
                stop(root,processes(root));restore_files(snapshot,root);restart(root,service);state.unlink(missing_ok=True)
            except BaseException as rollback:
                raise RuntimeError('Update failed and automatic recovery could not finish. Backup: '+str(snapshot)+'. Run update.py restore --backup with that path.') from rollback
            raise RuntimeError('Update failed; the previous Hub files, dependencies and local databases were restored. Backup: '+str(snapshot)) from error
        restart(root,service)
        raise


def restore_install(root,snapshot=None):
    root=validate_install(root);state=root/'.run/update-state.json'
    pending=json.loads(state.read_text()) if state.exists() else None
    snapshot=Path(snapshot) if snapshot else Path(pending['backup']) if pending else latest_backup(root)
    data=validate_backup(snapshot,root)
    active=processes(root);service=next((item for item in active if item['kind']=='server'),None)
    service=service or (pending['service'] if pending else data.get('service'))
    stop(root,active)
    try:rescue=backup(root,'before-restore',service,allow_damaged=True)
    except BaseException:
        restart(root,service);raise
    json_file(state,{'backup':str(snapshot.resolve()),'service':service})
    try:
        restore_files(snapshot,root);restart(root,service);state.unlink(missing_ok=True)
    except BaseException:
        stop(root,processes(root));restore_files(rescue,root);restart(root,service)
        raise RuntimeError('Restore failed. The state from before this restore was recovered; backup: '+str(rescue))
    print('Restore complete. '+('The Hub is running.' if service else 'The Hub remains stopped.'))
    return rescue


def backup_install(root):
    active=processes(root);service=next((item for item in active if item['kind']=='server'),None)
    stop(root,active)
    try:return backup(root,'manual',service)
    finally:restart(root,service)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',nargs='?',choices=('update','backup','restore'),default='update')
    parser.add_argument('--install',type=Path,default=ROOT,help='Existing Hub directory; its folder name is not changed')
    parser.add_argument('--archive',type=Path,help='Use a downloaded deployment ZIP instead of GitHub latest')
    parser.add_argument('--checksum',type=Path,help='Checksum file for --archive; defaults to ZIP.sha256')
    parser.add_argument('--backup',type=Path,help='Specific restore snapshot; otherwise the last update/manual backup')
    args=parser.parse_args();root=validate_install(args.install)
    with maintenance(root):
        if args.command=='backup':backup_install(root)
        elif args.command=='restore':restore_install(root,args.backup)
        else:
            with tempfile.TemporaryDirectory(prefix='journey-hub-update-') as temporary:
                # First upgrade: run the bundled updater from the newly extracted release.
                if not args.archive and ROOT!=root and (ROOT/'release-manifest.json').is_file():source=ROOT
                else:
                    archive=args.archive or latest_release(temporary)
                    source=unpack(archive,Path(temporary)/'release',args.checksum)
                update_install(root,source)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,RuntimeError,sqlite3.Error,zipfile.BadZipFile,subprocess.SubprocessError) as error:
        raise SystemExit('Maintenance failed: '+str(error)) from None
