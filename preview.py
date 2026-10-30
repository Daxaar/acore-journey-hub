#!/usr/bin/env python3
"""Rebuild and serve a disposable preview using copies of an existing installation's data."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import zipfile

from package_release import ROOT, build

STATE_FILES = ('deployment.json', 'groups.json', 'watchlist.json', 'watch-notes.json',
               'settings.json', 'client-models.json', 'gear-planner.json')


def copy_state(live, app):
    for name in STATE_FILES:
        source = live/name
        if source.is_file():shutil.copy2(source, app/name)
    if (live/'assets').is_dir():
        shutil.copytree(live/'assets', app/'assets', ignore=shutil.ignore_patterns('crafting-catalogue.json'))
    for source in live.glob('*.sqlite3'):
        if source.name == 'crafting-reviews.sqlite3':continue
        with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as original:
            with sqlite3.connect(app/source.name) as target:original.backup(target)


def stop_previous(record):
    if not record.exists():return
    previous = json.loads(record.read_text())
    pid = int(previous['pid'])
    command = Path(f'/proc/{pid}/cmdline')
    if command.exists():
        expected = str(Path(previous['app'])/'dashboard.py').encode()
        if expected not in command.read_bytes().split(b'\0'):
            raise RuntimeError('Recorded PID belongs to a different process; refusing to stop it.')
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            if not command.exists():break
            stat = Path(f'/proc/{pid}/stat')
            if stat.exists() and stat.read_text().split(') ',1)[1].startswith('Z'):break
            time.sleep(.1)
        else:raise RuntimeError('Previous preview did not stop; see .run/preview.log.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', type=Path, default=ROOT.parent/'character-hub-live')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    live = args.live.expanduser().resolve()
    if not (live/'dashboard.py').is_file():parser.error('Choose an existing installation with --live.')
    if not 1024 <= args.port <= 65535:parser.error('Choose a port between 1024 and 65535.')
    archive = build()
    run = ROOT/'.run';run.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='preview-', dir=run))
    with zipfile.ZipFile(archive) as bundle:bundle.extractall(stage)
    app = stage/'character-hub'
    copy_state(live, app)
    # Always use a separate loopback listener; never copy the live network configuration.
    record = run/f'preview-{args.port}.json'
    stop_previous(record)
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:probe.bind(('127.0.0.1', args.port))
        except OSError as exc:raise RuntimeError(f'Port {args.port} is occupied by another server. Stop that test server or choose --port.') from exc
    python = ROOT/'.venv/bin/python'
    if not python.is_file():python = Path(sys.executable)
    log = run/'preview.log'
    with log.open('ab') as output:
        process = subprocess.Popen([str(python), str(app/'dashboard.py'), '--listen', '127.0.0.1',
                                    '--port', str(args.port)], cwd=app, stdout=output,
                                   stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    url = f'http://localhost:{args.port}'
    for _ in range(100):
        if process.poll() is not None:raise RuntimeError(f'Preview failed to start. See {log}')
        try:
            with urlopen(f'http://127.0.0.1:{args.port}/professions.js', timeout=1) as response:
                if response.status == 200 and response.read() == (app/'static/professions.js').read_bytes():
                    time.sleep(.2)
                    if process.poll() is None:break
        except OSError:pass
        time.sleep(.1)
    else:
        process.terminate()
        raise RuntimeError(f'Preview did not become ready. See {log}')
    record.write_text(json.dumps({'pid':process.pid, 'app':str(app), 'url':url}, indent=2)+'\n')
    print('Preview ready: '+url+'/professions', flush=True)
    print('Live installation unchanged. Preview edits stay in '+str(app), flush=True)


if __name__ == '__main__':
    try:main()
    except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:sys.exit(str(exc))
