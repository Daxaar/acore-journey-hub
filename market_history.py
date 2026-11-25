"""Archive one Forever market overview and read it locally."""
import argparse
from contextlib import closing
import fcntl
import gzip
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sqlite3
import statistics
import tempfile
import time
from urllib.request import Request, urlopen

MARKET = 'eu-2-111'
URL = 'https://auctionhouse.tk.gg/api/m/' + MARKET
DEFAULT_ITEMS = (2592, 2589, 4306, 2770, 2771, 2447)
METRICS = ('ask', 'median', 'listed', 'vol24', 'sure24')
LIMIT = 20 * 1024 * 1024


def data_root():
    return Path(os.environ.get('JOURNEY_HUB_MARKET_DATA',
                               Path.home() / '.local/share/journey-hub-market'))


def connect(root, readonly=False):
    db = root / 'market.sqlite3'
    connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) if readonly else sqlite3.connect(db)
    connection.row_factory = sqlite3.Row
    return connection


def parse_snapshot(raw):
    payload = json.loads(raw)
    house = payload['house']
    stamp = payload['t']
    if (house['key'], house['region'], house['grp'], house['faction'], house['house']) != (MARKET, 'eu', 2, 'alliance', 111):
        raise ValueError('Unexpected market identity.')
    if type(stamp) is not int or stamp <= 0 or stamp != house['snapshot'] or stamp > int(time.time()*1000)+300000:
        raise ValueError('Unexpected market snapshot timestamp.')
    fields = payload['f']
    if len(set(fields)) != len(fields) or not set(METRICS[:4]).issubset(fields):
        raise ValueError('Unexpected market columns.')
    indices = [fields.index(k) if k in fields else None for k in METRICS]
    rows, seen = [], set()
    for item in payload['items']:
        item_id, name, values = item['id'], item['name'], item['o']
        if type(item_id) is not int or not 0 < item_id <= 4294967295 or item_id in seen:
            raise ValueError('Invalid or duplicate item ID.')
        if not isinstance(name, str) or not name or not isinstance(values, list) or len(values) != len(fields):
            raise ValueError('Invalid item metadata.')
        metrics = [values[i] if i is not None else None for i in indices]
        if any(v is not None and (type(v) is not int or v < 0) for v in metrics):
            raise ValueError('Invalid price or volume.')
        asks = item.get('s', [])
        positives = [v for v in asks if type(v) is int and v > 0]
        proposal = round(statistics.median(positives)) if len(positives) >= 6 else None
        rows.append((stamp, item_id, name, *metrics, proposal))
        seen.add(item_id)
    if not rows:
        raise ValueError('The market overview has no items.')
    return stamp, rows


def archive(root, raw):
    stamp, rows = parse_snapshot(raw)
    with closing(connect(root)) as db, db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
          stamp INTEGER PRIMARY KEY, fetched_at INTEGER NOT NULL, sha256 TEXT NOT NULL, item_count INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS observations (
          stamp INTEGER NOT NULL, item_id INTEGER NOT NULL, name TEXT NOT NULL,
          ask INTEGER, median INTEGER, listed INTEGER, vol24 INTEGER, sure24 INTEGER, proposal INTEGER,
          PRIMARY KEY(stamp,item_id));
        CREATE INDEX IF NOT EXISTS observation_item_history ON observations(item_id,stamp);
        """)
        digest = hashlib.sha256(raw).hexdigest()
        previous = db.execute('SELECT sha256 FROM snapshots WHERE stamp=?', (stamp,)).fetchone()
        if previous:
            return stamp, 0
        directory = root / 'raw' / MARKET
        directory.mkdir(parents=True, exist_ok=True)
        dest = directory / f'{stamp}.json.gz'
        if dest.exists():
            raw = gzip.decompress(dest.read_bytes())
            digest = hashlib.sha256(raw).hexdigest()
            archived_stamp, rows = parse_snapshot(raw)
            if archived_stamp != stamp:
                raise ValueError('Archive filename and snapshot disagree.')
        else:
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
                temp = Path(output.name)
                try:
                    output.write(gzip.compress(raw, compresslevel=6, mtime=0))
                    output.flush()
                    os.fsync(output.fileno())
                    temp.replace(dest)
                finally:
                    temp.unlink(missing_ok=True)
        db.executemany('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)', rows)
        db.execute('INSERT INTO snapshots VALUES (?,?,?,?)', (stamp, int(time.time()*1000), digest, len(rows)))
    return stamp, len(rows)


def collect(root):
    request = Request(URL, headers={'User-Agent': 'JourneyHub-market-preview/0.1', 'Accept': 'application/json'})
    with urlopen(request, timeout=25) as response:
        raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Market response exceeds the size limit.')
    return archive(root, raw)


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true', help='Collect every hour while this process is running.')
    args = parser.parse_args()
    root = data_root().resolve()
    root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('market')
    logger.setLevel(logging.INFO)
    log = RotatingFileHandler(root/'collector.log', maxBytes=262144, backupCount=2)
    log.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(log)
    with (root/'collector.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(1, 'Market collector already running.\n')
        if args.watch and (root/'market.sqlite3').is_file():
            with closing(connect(root, readonly=True)) as db:
                latest = db.execute('SELECT MAX(fetched_at) FROM snapshots').fetchone()[0]
            if latest is not None:
                delay = min(3600, max(0, 3600 - (time.time() - latest/1000)))
                logger.info('Next scheduled collection in %.0f seconds', delay)
                time.sleep(delay)
        while True:
            try:
                stamp, rows = collect(root)
                logger.info('Snapshot %s, %s new item observations', stamp, rows)
                print(f'Snapshot {stamp}, {rows} new item observations', flush=True)
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
                logger.warning('Collection failed: %s', error)
                if not args.watch:
                    parser.exit(1, f'Collection failed: {error}\n')
            if not args.watch:
                return
            time.sleep(3600)


if __name__ == '__main__':
    run()
