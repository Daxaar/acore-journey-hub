"""Classify AHBot Plus candidate coverage without changing prices."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import time

from anniversary_market import fallback_prices
from armory import read_inventory_sql
from auctions import PREFIX
from market_history import connect, data_root
from market_policy import HOUR, bag_sale_prices, local_catalogue, prices_from_history
from mysql_access import DatabaseError


def stock_items(reader):
    location = os.environ.get('JOURNEY_HUB_MARKET_PRICE_DIR')
    if location:
        path = Path(location) / 'stock-catalogue.txt'
        try:
            items = {int(line) for line in path.read_text().splitlines()}
            if not items or len(items) > 100000 or not all(0 < i <= 4294967295 for i in items):
                raise ValueError('Invalid AHBot Plus catalogue.')
            return items, 'configured_candidates'
        except FileNotFoundError:
            pass
    owners = os.environ.get('JOURNEY_HUB_MARKET_BOT_IDS', '').split(',')
    if not all(owner.isascii() and owner.isdecimal() and 0 < int(owner) <= 4294967295 for owner in owners):
        return set(), 'unavailable'
    ids = ','.join(str(int(owner)) for owner in owners)
    rows = reader(PREFIX + f"""
      SELECT JSON_OBJECT('id',i.itemEntry)
      FROM acore_characters.auctionhouse a
      JOIN acore_characters.item_instance i ON i.guid=a.itemguid
      WHERE a.itemowner IN ({ids}) AND a.time>UNIX_TIMESTAMP()
      GROUP BY i.itemEntry;
      COMMIT;
    """)
    return {row['id'] for row in rows}, 'observed_listings'


def coverage(reader=read_inventory_sql):
    items, scope = stock_items(reader)
    if scope == 'unavailable':
        return {'scope': scope}
    try:
        with closing(connect(data_root().resolve(), readonly=True)) as db:
            stamp = db.execute('SELECT MAX(stamp) FROM snapshots').fetchone()[0]
            if stamp is None:
                return {'scope': 'unavailable'}
            seen = {row[0] for row in db.execute('SELECT DISTINCT item_id FROM observations')}
            live = dict(db.execute('SELECT item_id,proposal FROM observations WHERE stamp=? AND proposal>0', (stamp,)))
            historical = prices_from_history(db, stamp)
    except sqlite3.Error as error:
        raise DatabaseError('Local market history is unavailable.') from error

    bags = bag_sale_prices(data_root().resolve(), stamp)
    fresh = int(time.time()*1000) - stamp < 3*HOUR
    anniversary = fallback_prices(data_root().resolve(), int(time.time()*1000))
    found = items & (seen | anniversary.keys())
    eligible = local_catalogue(found, reader, allow_unstackable=True)
    counts = dict(live=0, historical_only=0, policy_excluded=0,
                  insufficient_data=0, anniversary=0, never_seen=len(items-found))
    for item in found:
        row = eligible.get(item)
        if not row:
            counts['policy_excluded'] += 1
            continue
        cap = min(1_000_000_000, (2**32-1)//max(1,row['stack'])//2)
        current = live.get(item) if fresh else None
        past = historical.get(item)
        if row['stack']<=1:
            current = bags.get(item) if row['bag'] and fresh else None
            past = bags.get(item) if row['bag'] else None
        if current and max(current, row['vendor']) <= cap:
            counts['live'] += 1
        elif past and max(past, row['vendor']) <= cap:
            counts['historical_only'] += 1
        elif anniversary.get(item) and max(anniversary[item], row['vendor'])<=cap:
            counts['anniversary'] += 1
        elif current or past or anniversary.get(item) or (row['stack']<=1 and not row['bag']):
            counts['policy_excluded'] += 1
        else:
            counts['insufficient_data'] += 1
    return {'scope': scope, 'total': len(items), 'snapshot': stamp, **counts}
