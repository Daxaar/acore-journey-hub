"""Record actual Azeroth-2 Alliance listing prices for later comparison."""
from contextlib import closing
import sqlite3
import time

from armory import read_inventory_sql
from auctions import PREFIX
from market_history import DEFAULT_ITEMS, connect, data_root


def sample(reader=read_inventory_sql, now=None):
    stamp = int(time.time()*1000) if now is None else now
    bucket = stamp // 3_600_000 * 3_600_000
    ids = ','.join(map(str, DEFAULT_ITEMS))
    rows = reader(PREFIX + f"""
        SELECT JSON_OBJECT('id',i.itemEntry,'ask',ROUND(MIN(a.buyoutprice/i.count),2),
                           'units',SUM(i.count),'listings',COUNT(*))
        FROM acore_characters.auctionhouse a
        JOIN acore_characters.item_instance i ON i.guid=a.itemguid
        WHERE a.houseid=2 AND a.time>UNIX_TIMESTAMP() AND a.buyoutprice>0
          AND i.count>0 AND i.itemEntry IN ({ids}) GROUP BY i.itemEntry;
        COMMIT;
    """)
    root = data_root().resolve()
    with closing(connect(root)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS local_listing_history (
           hour INTEGER NOT NULL, stamp INTEGER NOT NULL, item_id INTEGER NOT NULL,
           ask_copper REAL, units INTEGER NOT NULL, listings INTEGER NOT NULL,
           PRIMARY KEY(hour,item_id))""")
        by_id = {row['id']: row for row in rows}
        db.executemany('INSERT OR IGNORE INTO local_listing_history VALUES (?,?,?,?,?,?)', (
            (bucket, stamp, item, by_id.get(item, {}).get('ask'),
             by_id.get(item, {}).get('units', 0), by_id.get(item, {}).get('listings', 0))
            for item in DEFAULT_ITEMS
        ))
    return len(DEFAULT_ITEMS)


if __name__ == '__main__':
    print(f'Sampled {sample()} local pilot items.')
