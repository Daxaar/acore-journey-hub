"""Browse archived Forever listings with optional read-only Azeroth-2 comparisons."""
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
import gzip
import json
import os
from pathlib import Path
import sqlite3
import time

from auctions import PREFIX, ROOT, filters
from armory import ITEM_TOOLTIP_FIELDS, read_inventory_sql
from market_history import MARKET, connect, data_root
from mysql_access import DatabaseError

QUALITIES = {'POOR':0,'COMMON':1,'UNCOMMON':2,'RARE':3,'EPIC':4,'LEGENDARY':5,'ARTIFACT':6,'HEIRLOOM':7}
CATEGORIES = {'consumable':0,'consumables':0,'container':1,'containers':1,'weapon':2,'weapons':2,
              'gem':3,'gems':3,'armor':4,'reagent':5,'reagents':5,'projectile':6,'trade goods':7,
              'recipe':9,'recipes':9,'quiver':11,'quest':12,'key':13,'miscellaneous':15,'glyph':16}
PAGE_SIZE = 60


@lru_cache(maxsize=2)
def archived_items(root, stamp):
    with gzip.open(root/'raw'/MARKET/f'{stamp}.json.gz','rb') as source:
        payload = json.load(source)
    fields = {field:i for i,field in enumerate(payload['f'])}
    result = {}
    for row in payload['items']:
        def value(field):
            pos = fields.get(field)
            return row['o'][pos] if pos is not None else None
        if not value('listed'):
            continue
        item = {'id':row['id'],'name':row['name'],'quality':QUALITIES.get(row.get('q'),1),
                'level':row.get('lvl') or 0, 'description':'', 'required_level':0,'skill_rank':0,
                'required_skill':0,'sell_price':row.get('sell') or 0,
                'category':CATEGORIES.get((row.get('cls') or '').lower()),
                'quantity':value('listed'),'unit_price':value('ask'),'auctions':value('listings') or 0,
                'median':value('median'),'last_sold_price':value('lastSoldP'),'last_sold_at':value('lastSoldT')}
        result[item['id']]=item
    return result


@lru_cache(maxsize=2)
def local_catalogue(ids, minute):
    mapping = {}
    for offset in range(0,len(ids),2000):
        subset = ','.join(map(str,ids[offset:offset+2000]))
        rows = read_inventory_sql(PREFIX + f"""
            SELECT JSON_OBJECT('id',entry,'category',class,'subclass',subclass,'slot',InventoryType,
                'displayid',displayid,'required_level',RequiredLevel,'skill_rank',RequiredSkillRank,
                'required_skill',RequiredSkill)
            FROM acore_world.item_template WHERE entry IN ({subset}); COMMIT;
        """)
        mapping.update((row['id'],row) for row in rows)
    return mapping


@lru_cache(maxsize=1)
def icons():
    try:
        return json.loads((ROOT/'assets/item-metadata.json').read_text()).get('icons',{})
    except (OSError,ValueError):
        return {}


def published_prices():
    directory = os.environ.get('JOURNEY_HUB_MARKET_PRICE_DIR')
    if not directory:
        return {}
    try:
        return {item:price for item,price in (
            tuple(map(int,line.split(','))) for line in (Path(directory)/'prices.csv').read_text().splitlines())}
    except (OSError,ValueError):
        return {}


def local_asks(items):
    if not items:
        return {}
    ids = ','.join(str(item['id']) for item in items)
    return {row['id']:row['ask'] for row in read_inventory_sql(PREFIX + f"""
        SELECT JSON_OBJECT('id',i.itemEntry,'ask',ROUND(MIN(a.buyoutprice/i.count),2))
        FROM acore_characters.auctionhouse a
        JOIN acore_characters.item_instance i ON i.guid=a.itemguid
        WHERE a.houseid IN (1,2,3) AND a.time>UNIX_TIMESTAMP() AND a.buyoutprice>0 AND i.count>0
          AND i.itemEntry IN ({ids})
        GROUP BY i.itemEntry; COMMIT;
    """)}


def local_tooltips(items):
    ids = ','.join(str(item['id']) for item in items if item['local_match'])
    if not ids:
        return {}
    fields = ','.join(f"'{field}',t.{field}" for field in ITEM_TOOLTIP_FIELDS)
    return {row['id']: row for row in read_inventory_sql(PREFIX + f"""
        SELECT JSON_OBJECT('id',t.entry,'description',t.description,
                           'sell_price',t.SellPrice,{fields})
        FROM acore_world.item_template t WHERE t.entry IN ({ids}); COMMIT;
    """)}


def get_forever_auctions(params, detail=False):
    values, _, page = filters(params, detail)
    root = data_root().resolve()
    try:
        with closing(connect(root,readonly=True)) as db:
            stamp = db.execute('SELECT MAX(stamp) FROM snapshots').fetchone()[0]
        if stamp is None:
            raise DatabaseError('No Forever snapshot has been archived yet.')
        archive = archived_items(root,stamp)
    except (OSError, ValueError, KeyError, IndexError, sqlite3.Error, EOFError) as exc:
        raise DatabaseError('The Forever archive is unavailable.') from exc
    try:
        local = local_catalogue(tuple(archive), int(time.monotonic()//300))
    except DatabaseError:
        local = None
    term = values.get('q','').strip().casefold()
    limits = {k:int(values[k]) for k in ('category','quality','min','max') if values.get(k)}
    classes = {int(x) for x in values.get('subclass','').split(',') if x}
    slots = {int(x) for x in values.get('slot','').split(',') if x}
    items = []
    candidates = (archive.get(int(values['id'])),) if detail else archive.values()
    for source in candidates:
        if not source:
            continue
        item = dict(source)
        match = (local or {}).get(item['id'])
        if match:
            item.update(match)
            item['icon'] = icons().get(str(item['displayid']))
        item['local_match'] = bool(match) if local is not None else None
        if not detail and (
            term and term not in item['name'].casefold() and term != str(item['id'])
            or 'category' in limits and item['category']!=limits['category']
            or 'quality' in limits and item['quality']!=limits['quality']
            or not limits.get('min',0)<=item['level']<=limits.get('max',1000)
            or classes and item.get('subclass') not in classes
            or slots and item.get('slot') not in slots
        ):
            continue
        items.append(item)
    order = values.get('sort','name')
    field = {'price':'unit_price','quantity':'quantity','auctions':'auctions','level':'level','skill':'skill_rank','name':'name'}[order.rsplit('_',1)[0]]
    reverse = order.endswith('_desc') or order in ('quantity','auctions','level','skill')
    items.sort(key=lambda item: (item['name'].casefold(),item['id']))
    items.sort(key=lambda item: (item[field].casefold() if field=='name' else (item[field] or 0)),reverse=reverse)
    if field=='unit_price':
        items.sort(key=lambda item:item['unit_price'] is None)
    totals = {'items':len(items),'auctions':sum(item['auctions'] for item in items),
              'quantity':sum(item['quantity'] for item in items)}
    items = items[:1] if detail else items[(page-1)*PAGE_SIZE:page*PAGE_SIZE]
    try:
        asks = local_asks(items)
    except DatabaseError:
        asks = {}
    try:
        tooltips = local_tooltips(items)
    except DatabaseError:
        tooltips = {}
    published = published_prices()
    for item in items:
        item.update(tooltips.get(item['id'], {}))
        item['local_ask'] = asks.get(item['id'])
        item['published_price'] = published.get(item['id'])
    return {'items':items,'totals':totals,'page':page,'page_size':PAGE_SIZE,
            'refreshed_at':datetime.fromtimestamp(stamp/1000,timezone.utc).isoformat()}
