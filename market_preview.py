"""Compare archived prices with local Alliance auctions."""
from contextlib import closing
from functools import lru_cache
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from anniversary_market import feed_status, realm_matches
from armory import read_inventory_sql
from auctions import PREFIX
from market_history import DEFAULT_ITEMS, MARKET, connect, data_root
from mysql_access import DatabaseError
from market_policy import bag_sale_prices


def integration_status(snapshot):
    # Step 2 has no publisher or module acknowledgement.
    age = max(0, int(time.time()*1000) - snapshot['stamp']) if snapshot else None
    result = {
        'feed': 'waiting' if age is None else 'stale' if age >= 10800000 else 'recent',
        'publisher': 'not_connected',
        'active_price_set': None,
        'feeds': {
            'forever': {'label':'Forever EU PvE Alliance','stamp':snapshot['stamp'] if snapshot else None,
                        'items':snapshot['item_count'] if snapshot else None,
                        'health':'waiting' if age is None else 'stale' if age>=10800000 else 'recent'},
            **feed_status(data_root().resolve(), int(time.time()*1000)),
        },
    }
    directory = os.environ.get('JOURNEY_HUB_MARKET_PRICE_DIR')
    if directory:
        root = Path(directory)
        try:
            status = json.loads((root/'status.json').read_text())
            prices = (root/'prices.csv').read_bytes()
            digest = hashlib.sha256(prices).hexdigest()
            result['publisher'] = status['mode']
            result['active_price_set'] = {
                'digest': digest,
                'count': prices.count(b'\n'),
                'generated_at': status.get('generated_at') if status.get('sha256')==digest else None,
                'reason': status.get('reason'),
                'anniversary_items': status.get('anniversary_items') if status.get('sha256')==digest else None,
            }
        except (OSError, ValueError, KeyError, TypeError):
            result['publisher'] = 'unavailable'
    return result


@lru_cache(maxsize=2)
def archived_sales(root, stamp):
    path = root / 'raw' / MARKET / f'{stamp}.json.gz'
    with gzip.open(path, 'rb') as source:
        snapshot = json.load(source)
    fields = snapshot['f']
    if not {'lastSoldT', 'lastSoldP'}.issubset(fields):
        return {}
    date, price = fields.index('lastSoldT'), fields.index('lastSoldP')
    return {item['id']: (item['o'][date], item['o'][price]) for item in snapshot['items']}


def get_market_preview(search, reader=read_inventory_sql):
    if len(search) > 80:
        raise ValueError('Search with up to 80 characters.')
    if not (data_root() / 'market.sqlite3').is_file():
        return {'market': MARKET, 'snapshot': None, 'rows': [], 'status': integration_status(None)}
    try:
        with closing(connect(data_root().resolve(), readonly=True)) as db:
            snapshot = db.execute('SELECT stamp,item_count FROM snapshots ORDER BY stamp DESC LIMIT 1').fetchone()
            if snapshot is None:
                return {'market': MARKET, 'snapshot': None, 'rows': [], 'status': integration_status(None)}
            sql = 'SELECT * FROM observations WHERE stamp=?'
            if search:
                rows = db.execute(sql + """ AND (instr(lower(name),lower(?))>0 OR CAST(item_id AS TEXT)=?)
                    ORDER BY name,item_id LIMIT 40""", (snapshot['stamp'], search, search)).fetchall()
            else:
                slots = ','.join('?' for _ in DEFAULT_ITEMS)
                rows = db.execute(sql + f' AND item_id IN ({slots})', (snapshot['stamp'], *DEFAULT_ITEMS)).fetchall()
    except sqlite3.Error as error:
        raise DatabaseError('Local market history is unavailable.') from error

    rows = [dict(row) for row in rows]
    published, anniversary_ids = {}, None
    directory = os.environ.get('JOURNEY_HUB_MARKET_PRICE_DIR')
    if directory:
        try:
            folder = Path(directory)
            manifest = json.loads((folder/'status.json').read_text())
            raw = (folder/'prices.csv').read_bytes()
            published = dict(tuple(map(int,line.split(','))) for line in raw.decode('ascii').splitlines())
            if manifest.get('sha256') == hashlib.sha256(raw).hexdigest():
                anniversary_ids = set(manifest.get('anniversary_ids', []))
        except (OSError, ValueError, TypeError):
            pass
    seen = {row['item_id'] for row in rows}
    try:
        extra = realm_matches(data_root().resolve(), search or '23438', 40-len(rows))
    except (OSError, ValueError, KeyError, TypeError, EOFError):
        extra = []
    for item, name in extra:
        if item not in seen:
            rows.append(dict(item_id=item,name=name,proposal=None,ask=None,median=None,
                             listed=None,vol24=None,sure24=None))

    local = {}
    local_error = False
    def safe_read(sql):
        nonlocal local_error
        try:
            return reader(sql)
        except DatabaseError:
            local_error = True
            return []
    if rows:
        ids = ','.join(str(row['item_id']) for row in rows)
        local = {row['id']: row for row in safe_read(PREFIX + f"""
        SELECT JSON_OBJECT('id',t.entry,'name',t.name,'vendor',t.SellPrice,'bonding',t.bonding,'stack',t.stackable,'bag',t.class=1 AND t.subclass=0,'ask',a.ask,'units',a.units)
        FROM acore_world.item_template t
        LEFT JOIN (
          SELECT i.itemEntry, ROUND(MIN(a.buyoutprice/i.count),2) AS ask, SUM(i.count) AS units
          FROM acore_characters.auctionhouse a JOIN acore_characters.item_instance i ON i.guid=a.itemguid
          WHERE a.houseid=2 AND a.time>UNIX_TIMESTAMP() AND a.buyoutprice>0 AND i.count>0 AND i.itemEntry IN ({ids})
          GROUP BY i.itemEntry
        ) a ON a.itemEntry=t.entry WHERE t.entry IN ({ids});
        COMMIT;
        """)}
    try:
        sales = archived_sales(data_root().resolve(), snapshot['stamp']) if rows else {}
        bags = bag_sale_prices(data_root().resolve(), snapshot['stamp']) if rows else {}
    except (OSError, ValueError, KeyError, IndexError, EOFError):
        sales, bags = {}, {}
    result = []
    for row in rows:
        item = local.get(row['item_id'])
        proposal = None
        if item and item['bonding'] in (0, 2, 3):
            estimate = row['proposal'] if item['stack']>1 else bags.get(row['item_id']) if item['bag'] else None
            if estimate:
                price = max(estimate, item['vendor'])
                if price <= min(1_000_000_000, (2**32-1)//max(1,item['stack'])//2):
                    proposal = price
        sale_at, sale_price = sales.get(row['item_id'], (None, None))
        published_price = published.get(row['item_id'])
        source = ('Unknown' if anniversary_ids is None else
                  'Anniversary' if row['item_id'] in anniversary_ids else 'Forever') if published_price else None
        result.append(dict(row, local=item, proposed=proposal,
                           published_price=published_price, price_source=source,
                           last_sold_at=sale_at, last_sold_price=sale_price))
    if not search:
        result.sort(key=lambda row: DEFAULT_ITEMS.index(row['item_id']) if row['item_id'] in DEFAULT_ITEMS else len(DEFAULT_ITEMS))
    return {'market': MARKET, 'snapshot': dict(snapshot), 'rows': result,
            'status': integration_status(snapshot), 'local_unavailable':local_error,
            'reset': None if local_error else reset_preview(safe_read)}


def reset_preview(reader):
    owners = os.environ.get('JOURNEY_HUB_MARKET_BOT_IDS','').split(',')
    if not all(owner.isascii() and owner.isdecimal() and 0 < int(owner) <= 4294967295 for owner in owners):
        return None
    ids = ','.join(str(int(owner)) for owner in owners)
    result = reader(PREFIX + f"""
      SELECT JSON_OBJECT('unbid',COALESCE(SUM(buyguid=0 AND lastbid=0),0),
                        'with_bid',COALESCE(SUM(buyguid<>0 OR lastbid<>0),0))
      FROM acore_characters.auctionhouse WHERE itemowner IN ({ids}) AND time>UNIX_TIMESTAMP();
      COMMIT;
    """)
    return result[0] if result else None


def list_snapshots(before):
    if not 0 < before <= 9223372036854775807:
        raise ValueError('Invalid snapshot cursor.')
    root = data_root().resolve()
    if not (root / 'market.sqlite3').is_file():
        return {'snapshots': [], 'next_before': None}
    with closing(connect(root, readonly=True)) as db:
        rows = [dict(row) for row in db.execute(
            'SELECT stamp,item_count,sha256 FROM snapshots WHERE stamp<? ORDER BY stamp DESC LIMIT 26',
            (before,))]
    return {'snapshots': rows[:25], 'next_before': rows[24]['stamp'] if len(rows) > 25 else None}


def download_snapshot(stamp, compressed):
    import gzip
    from market_history import LIMIT

    if not 0 < stamp <= 9223372036854775807:
        raise ValueError('Invalid snapshot timestamp.')
    root = data_root().resolve()
    if not (root / 'market.sqlite3').is_file():
        raise FileNotFoundError
    with closing(connect(root, readonly=True)) as db:
        if db.execute('SELECT 1 FROM snapshots WHERE stamp=?', (stamp,)).fetchone() is None:
            raise FileNotFoundError
    file = root / 'raw' / MARKET / f'{stamp}.json.gz'
    opener = open if compressed else gzip.open
    limit = LIMIT + 65536 if compressed else LIMIT
    with opener(file, 'rb') as source:
        body = source.read(limit + 1)
    if len(body) > limit:
        raise OSError('Archived snapshot exceeds download limit.')
    return body
