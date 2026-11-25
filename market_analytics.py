"""Read and record market coverage without modifying Azeroth-2."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from armory import read_inventory_sql
from auctions import PREFIX
from market_history import connect, data_root

HOUR = 3600000
RANGES = {'24h': 24, '7d': 168, '30d': 720}


def sample_analytics(output, owners, reader=read_inventory_sql, now=None):
    now = int(time.time()*1000) if now is None else now
    manifest = json.loads((output/'status.json').read_text())
    body = (output/'prices.csv').read_bytes()
    if manifest.get('sha256') != hashlib.sha256(body).hexdigest():
        return None
    anniversary = set(manifest.get('anniversary_ids', []))
    prices = [tuple(map(int,line.split(','))) for line in body.decode('ascii').splitlines()]
    if not prices or len(prices)>50000 or any(not 0<item<=4294967295 or not 0<price<=4294967295 for item,price in prices):
        raise ValueError('Invalid published prices.')
    if not owners or any(type(owner) is not int or not 0<owner<=4294967295 for owner in owners):
        raise ValueError('Invalid AHBot Plus owner IDs.')
    by_item = dict(prices)
    seller_ids = ','.join(map(str,owners))
    rows = reader(PREFIX + f"""
       SELECT JSON_ARRAY(i.itemEntry,i.count,a.buyoutprice,COUNT(*))
       FROM acore_characters.auctionhouse a
       JOIN acore_characters.item_instance i ON i.guid=a.itemguid
       WHERE a.itemowner IN ({seller_ids}) AND a.time>UNIX_TIMESTAMP()
       GROUP BY i.itemEntry,i.count,a.buyoutprice;
       COMMIT;
    """)
    data = dict.fromkeys(('total','covered','forever','anniversary'), 0)
    for item, stack, buyout, count in rows:
        data['total'] += count
        if item in by_item:
            data['covered'] += count
            if buyout == by_item[item]*stack:
                data['anniversary' if item in anniversary else 'forever'] += count
    with closing(connect(data_root().resolve())) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS auction_analytics (
            hour INTEGER PRIMARY KEY, stamp INTEGER NOT NULL, total INTEGER NOT NULL,
            covered INTEGER NOT NULL, forever INTEGER NOT NULL, anniversary INTEGER NOT NULL,
            published INTEGER NOT NULL, anniversary_items INTEGER NOT NULL)""")
        db.execute('INSERT OR REPLACE INTO auction_analytics VALUES (?,?,?,?,?,?,?,?)',
                   (now//HOUR*HOUR,now,*(int(data[k]) for k in ('total','covered','forever','anniversary')),
                    len(prices),len(anniversary)))
    return data


def analytics(window):
    if window not in RANGES:
        raise ValueError('Choose a valid market range.')
    root = data_root().resolve()
    if not (root/'market.sqlite3').is_file():
        return {'local':[],'imports':[],'top':[],'slow':[]}
    cutoff=int(time.time()*1000)-RANGES[window]*HOUR
    with closing(connect(root,readonly=True)) as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='auction_analytics'").fetchone()
        local=[dict(r) for r in db.execute('SELECT * FROM auction_analytics WHERE stamp>=? ORDER BY stamp',(cutoff,))] if exists else []
        imports=[dict(r) for r in db.execute('SELECT stamp,item_count FROM snapshots WHERE stamp>=? ORDER BY stamp',(cutoff,))]
        stamp=db.execute('SELECT MAX(stamp) FROM snapshots').fetchone()[0]
        top=[dict(r) for r in db.execute('''SELECT item_id,name,vol24,listed,sure24 FROM observations
             WHERE stamp=? AND vol24>0 ORDER BY vol24 DESC,item_id LIMIT 8''',(stamp,))]
        slow=[dict(r) for r in db.execute('''SELECT item_id,name,vol24,listed,sure24 FROM observations
             WHERE stamp=? AND listed>=10 AND vol24 IS NOT NULL
             ORDER BY CAST(vol24 AS REAL)/listed,listed DESC,item_id LIMIT 8''',(stamp,))]
    return {'local':local,'imports':imports,'top':top,'slow':slow,'sales_snapshot':stamp}
