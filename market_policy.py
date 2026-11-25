"""Generate and archive AHBot Plus price sets from local market observations."""
import argparse
from collections import defaultdict
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from statistics import median
import tempfile
import time

from anniversary_market import fallback_prices
from armory import read_inventory_sql
from auctions import PREFIX
from market_history import MARKET, connect, data_root

HOUR = 3_600_000
HISTORY_WINDOW = 30 * 24 * HOUR
MAX_OVERRIDES = 50_000


def replace_file(path, body):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        try:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def prices_from_history(db, now):
    samples = defaultdict(list)
    for item, ask in db.execute(
        'SELECT item_id,ask FROM observations WHERE stamp>=? AND ask>0',
        (now-HISTORY_WINDOW,)
    ):
        samples[item].append(ask)
    return {item: round(median(values)) for item, values in samples.items() if len(values)>=6}


def bag_sale_prices(root, stamp):
    """Regular bags can use a recent sale estimate backed by recent volume."""
    with gzip.open(root/'raw'/MARKET/f'{stamp}.json.gz', 'rb') as source:
        payload = json.load(source)
    fields = payload['f']
    required = ('vol24', 'lastSoldT', 'lastSoldP')
    if not set(required).issubset(fields):
        return {}
    volume_index, time_index, price_index = (fields.index(field) for field in required)
    prices = {}
    for item in payload['items']:
        if item.get('cls') != 'Container':
            continue
        values = item['o']
        volume, sold_at, copper = (values[index] for index in (volume_index, time_index, price_index))
        if (type(volume) is int and volume >= 5 and type(copper) is int and copper > 0
                and type(sold_at) is int and 0 <= stamp-sold_at <= 24*HOUR):
            prices[item['id']] = copper
    return prices


def local_catalogue(prices, reader, allow_unstackable=False):
    result = {}
    item_ids = sorted(prices)
    scope = '' if allow_unstackable else 'AND (stackable>1 OR (class=1 AND subclass=0))'
    for offset in range(0, len(item_ids), 500):
        ids = ','.join(map(str, item_ids[offset:offset+500]))
        rows = reader(PREFIX + f"""
        SELECT JSON_OBJECT('id',entry,'vendor',SellPrice,'stack',stackable,'bag',class=1 AND subclass=0)
        FROM acore_world.item_template
        WHERE entry IN ({ids}) AND bonding IN (0,2,3) {scope};
        COMMIT;
        """)
        for row in rows:
            result[row['id']] = row
    return result


def generate(mode, output, freshness_hours=3, now=None, reader=read_inventory_sql, allowed_items=None):
    now = int(time.time()*1000) if now is None else now
    output.mkdir(parents=True, exist_ok=True)
    status = output/'status.json'
    with closing(connect(data_root().resolve(), readonly=True)) as db:
        stamp = db.execute('SELECT MAX(stamp) FROM snapshots').fetchone()[0]
        if stamp is None:
            return {'mode': 'waiting', 'last_good_snapshot': None}
        if mode == 'live' and now-stamp < freshness_hours*HOUR:
            selected = 'live'
            candidates = dict(db.execute('SELECT item_id,proposal FROM observations WHERE stamp=? AND proposal>0',(stamp,)))
        else:
            selected = 'historical'
            candidates = prices_from_history(db, stamp)
    bags = bag_sale_prices(data_root().resolve(), stamp)
    anniversary = fallback_prices(data_root().resolve(), now, historical=mode=='historical')
    item_ids = candidates.keys() | bags.keys() | anniversary.keys()
    if allowed_items is not None:
        item_ids &= set(allowed_items)

        candidates = {item: price for item, price in candidates.items() if item in allowed_items}
    if not item_ids:
        result = {'mode':'holding', 'reason':'Insufficient market history for replacement', 'last_good_snapshot':stamp}
        replace_file(status,json.dumps(result).encode())
        return result
    catalogue = local_catalogue(item_ids, reader, allow_unstackable=True)
    prices = {}
    anniversary_ids = []
    for item, row in catalogue.items():
        stack = max(1, row['stack'])
        cap = min(1_000_000_000, (2**32-1)//stack//2)
        primary = candidates.get(item) if stack>1 else bags.get(item) if row['bag'] else None
        for source, estimate in (('forever', primary), ('anniversary', anniversary.get(item))):
            if not estimate:
                continue
            value = max(estimate, row['vendor'], 1)
            if value <= cap:
                prices[item] = value
                if source=='anniversary':
                    anniversary_ids.append(item)
                break
    if not prices or len(prices)>MAX_OVERRIDES:
        raise ValueError('No safe price set was generated. The last file is retained.')
    body = ''.join(f'{item},{price}\n' for item,price in sorted(prices.items())).encode()
    digest = hashlib.sha256(body).hexdigest()
    history = output/'published'
    history.mkdir(exist_ok=True)
    if not (history/f'{digest}.csv').exists():
        replace_file(history/f'{digest}.csv',body)
    target = output/'prices.csv'
    if not target.exists() or target.read_bytes()!=body:
        replace_file(target,body)
    result = {'mode':selected,'last_good_snapshot':stamp,'generated_at':now,'items':len(prices),'sha256':digest,
              'anniversary_items':len(anniversary_ids),'anniversary_ids':sorted(anniversary_ids)}
    replace_file(status,json.dumps(result).encode())
    return result


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('live','historical'),default='live')
    parser.add_argument('--freshness-hours',type=int,choices=range(1,25),default=3)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(generate(args.mode,args.output,args.freshness_hours)))
