"""Identify and manage only Python Hub processes in one installation (Linux/WSL)."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import tempfile
import time
from urllib.request import Request, urlopen


_children={}


class RuntimeErrorForHub(RuntimeError):
    pass


def process(pid, root):
    """Return a verified local Hub process; PID files alone are never trusted."""
    root=Path(root).resolve();proc=Path('/proc')/str(pid)
    try:
        if int(pid)==os.getpid() or proc.stat().st_uid!=os.getuid():return None
        args=[os.fsdecode(arg) for arg in (proc/'cmdline').read_bytes().split(b'\0') if arg]
        if len(args)<2 or not (proc/'exe').resolve().name.startswith('python'):return None
        index=1
        while index<len(args) and args[index].startswith('-'):
            if args[index] not in ('-u','-B','-E','-s','-S','-I','-O','-OO'):return None
            index+=1
        if index>=len(args):return None
        script=Path(args[index]);cwd=(proc/'cwd').resolve()
        script=(cwd/script).resolve() if not script.is_absolute() else script.resolve()
        kind='server' if script==root/'dashboard.py' else 'watcher' if script==root/'package_release.py' and '--watch' in args[index+1:] else None
        if not kind:return None
        stat=(proc/'stat').read_text().rsplit(') ',1)[1].split()
        if stat[0]=='Z':return None
        environment={}
        for entry in (proc/'environ').read_bytes().split(b'\0'):
            key,separator,value=entry.partition(b'=')
            if separator:
                key=os.fsdecode(key)
                if key.startswith(('JOURNEY_HUB_','CHARACTER_HUB_','LEMMINGS_','DOCKER_')) or key in ('PATH','MYSQL_PWD','PYTHONPATH'):
                    environment[key]=os.fsdecode(value)
        return {'pid':int(pid),'ticks':stat[19],'kind':kind,'python':args[0],
                'args':args[index+1:],'env':environment}
    except (OSError,ValueError,UnicodeError,IndexError):return None


def processes(root):
    if not Path('/proc').is_dir():raise RuntimeErrorForHub('Automatic Hub process management requires Linux or WSL.')
    result=[]
    for path in Path('/proc').iterdir():
        if path.name.isdigit():
            item=process(int(path.name),root)
            if item:result.append(item)
    if sum(item['kind']=='server' for item in result)>1:
        raise RuntimeErrorForHub('More than one Hub server uses this installation. Stop the extra server before updating.')
    return result


def stop(root, items):
    # Watchers stop first so they cannot rebuild files while an update is applied.
    for item in sorted(items,key=lambda value:value['kind']=='server'):
        current=process(item['pid'],root)
        if current and current['ticks']==item['ticks']:os.kill(item['pid'],signal.SIGTERM)
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if not any((current:=process(item['pid'],root)) and current['ticks']==item['ticks'] for item in items):break
        time.sleep(.05)
    else:raise RuntimeErrorForHub('The Hub did not stop. No update will be applied; check its service manager.')
    for pid,child in list(_children.items()):
        if child.poll() is not None:_children.pop(pid,None)
    if processes(root):raise RuntimeErrorForHub('A service manager restarted the Hub. Stop that manager before maintenance.')


def listener(root, service):
    network=Path(root)/'network.json'
    config=json.loads(network.read_text()) if network.exists() else {}
    address=config.get('listen','127.0.0.1');port=8765
    args=service['args']
    for index,arg in enumerate(args):
        if arg=='--port' and index+1<len(args):port=int(args[index+1])
        elif arg.startswith('--port='):port=int(arg.split('=',1)[1])
        elif arg=='--listen' and index+1<len(args):address=args[index+1]
        elif arg.startswith('--listen='):address=arg.split('=',1)[1]
    if address=='0.0.0.0':address='127.0.0.1'
    return address,port


def restart(root, service):
    if not service:return None
    root=Path(root).resolve();run=root/'.run'
    if run.is_symlink():raise RuntimeErrorForHub('The Hub runtime directory must not be a symlink.')
    run.mkdir(exist_ok=True)
    if (run/'update-server.log').is_symlink():raise RuntimeErrorForHub('The Hub restart log must not be a symlink.')
    environment=os.environ.copy();environment.update(service.get('env',{}))
    # Running start.sh preserves saved arguments and starts the package watcher too.
    with (run/'update-server.log').open('ab') as log:
        child=subprocess.Popen(['bash',str(root/'start.sh'),*service['args']],cwd=root,env=environment,
                               stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
    _children[child.pid]=child
    address,port=listener(root,service);deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        if child.poll() is not None:break
        try:
            request=Request(f'http://{address}:{port}/professions.js',headers={'Host':f'localhost:{port}'})
            with urlopen(request,timeout=1) as response:
                if response.status==200 and response.read()==(root/'static/professions.js').read_bytes():return child.pid
        except (OSError,ValueError):pass
        time.sleep(.1)
    # Do not leave a failed Hub or its watcher running through rollback.
    stop(root,processes(root))
    raise RuntimeErrorForHub('The updated Hub did not become ready. See .run/update-server.log.')


@contextmanager
def registered(root, server, args):
    """Record runtime details and allow maintenance to stop the Hub gracefully."""
    run=Path(root)/'.run'
    if run.is_symlink():raise RuntimeErrorForHub('The Hub runtime directory must not be a symlink.')
    run.mkdir(exist_ok=True)
    record=run/'server.json'
    data={'pid':os.getpid(),'args':list(args),'python':sys.executable}
    fd,temporary=tempfile.mkstemp(prefix='.server-',dir=run)
    try:
        with os.fdopen(fd,'w') as out:out.write(json.dumps(data)+'\n')
        os.replace(temporary,record)
    finally:Path(temporary).unlink(missing_ok=True)
    previous=signal.getsignal(signal.SIGTERM)
    def shutdown(signum,frame):
        threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,shutdown)
    try:yield
    finally:
        signal.signal(signal.SIGTERM,previous)
        try:
            if json.loads(record.read_text()).get('pid')==os.getpid():record.unlink()
        except (OSError,ValueError):pass
