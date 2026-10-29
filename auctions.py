"""Bounded, read-only AzerothCore auction browsing. No external market service."""
from datetime import datetime, timezone
from pathlib import Path
import json
import threading
import time

from armory import read_inventory_sql, ITEM_TOOLTIP_FIELDS
from mysql_access import DatabaseError

ROOT = Path(__file__).resolve().parent
HOUSES = {'all': (), 'alliance': (1, 2, 3), 'horde': (4, 5, 6), 'neutral': (7,)}
CATEGORIES = {0: 'Consumables', 1: 'Containers', 2: 'Weapons', 3: 'Gems', 4: 'Armor',
              5: 'Reagents', 6: 'Projectiles', 7: 'Trade goods', 9: 'Recipes',
              11: 'Quivers', 12: 'Quest items', 13: 'Keys', 15: 'Miscellaneous', 16: 'Glyphs'}

SORTS = {'name': 'name', 'price': 'unit_price IS NULL, unit_price',
         'quantity': 'quantity DESC', 'auctions': 'auctions DESC', 'level': 'level DESC',
         'name_desc': 'name DESC', 'price_desc': 'unit_price IS NULL, unit_price DESC',
         'skill': 'skill_rank DESC', 'skill_asc': 'skill_rank', 'quantity_asc': 'quantity', 'level_asc': 'level', 'auctions_asc': 'auctions'}
PREFIX = '''SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
'''
JOIN = '''FROM acore_characters.auctionhouse a
JOIN acore_characters.item_instance i ON i.guid=a.itemguid
JOIN acore_world.item_template t ON t.entry=i.itemEntry'''


def filters(params, detail=False):
    allowed = {'house', 'id', 'page'} if detail else {'house', 'q', 'category', 'quality', 'min', 'max', 'sort', 'page', 'subclass', 'slot'}
    if set(params) - allowed or any(len(v) != 1 for v in params.values()):
        raise ValueError('Provide one value per auction filter.')
    values = {k: v[0] for k, v in params.items()}
    house = values.get('house', 'all')
    if house not in HOUSES:
        raise ValueError('Choose a valid auction house.')
    where = ['a.time>UNIX_TIMESTAMP()', 'i.count>0']
    if HOUSES[house]:
        where.append('a.houseid IN (' + ','.join(map(str, HOUSES[house])) + ')')
    page = int(values.get('page', '1'))
    if not 1 <= page <= 10000:
        raise ValueError('Choose a page from 1 to 10000.')
    if detail:
        entry = int(values.get('id', '0'))
        if not 1 <= entry <= 4294967295:
            raise ValueError('Choose a valid item ID.')
        where.append(f'i.itemEntry={entry}')
    else:
        term = values.get('q', '')
        if len(term) > 100 or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in term):
            raise ValueError('Search with up to 100 printable characters.')
        term = term.strip()
        if term:
            # LOCATE treats percent, quotes and underscores as literal search text.
            literal = 'CONVERT(0x' + term.encode('utf-8').hex() + ' USING utf8mb4)'
            where.append(f'(LOCATE({literal},t.name)>0' + (f' OR i.itemEntry={int(term)}' if term.isascii() and term.isdigit() and len(term) <= 10 else '') + ')')
        for key, column, lower, upper in [('category', 't.class', 0, 16), ('quality', 't.Quality', 0, 7),
                                          ('min', 't.ItemLevel', 0, 1000), ('max', 't.ItemLevel', 0, 1000)]:
            if values.get(key, '') != '':
                number = int(values[key])
                if not lower <= number <= upper or (key == 'category' and number not in CATEGORIES):
                    raise ValueError('Invalid auction filter range.')
                where.append(f'{column}{">=" if key == "min" else "<=" if key == "max" else "="}{number}')
        for key, column, upper in [('subclass', 't.subclass', 20), ('slot', 't.InventoryType', 28)]:
            if values.get(key, '') != '':
                if values.get('category', '') == '':
                    raise ValueError('Choose a category before a subcategory or slot.')
                parts = values[key].split(',')
                if not 1 <= len(parts) <= 20 or any(not part.isascii() or not part.isdigit() or not 0 <= int(part) <= upper for part in parts):
                    raise ValueError('Choose a valid item subcategory or equipment slot.')
                where.append(column + ' IN (' + ','.join(str(int(part)) for part in parts) + ')')
        if values.get('min') and values.get('max') and int(values['min']) > int(values['max']):
            raise ValueError('Minimum level must not exceed maximum level.')
        if values.get('sort', 'name') not in SORTS:
            raise ValueError('Choose a valid auction sort.')
    return values, ' AND '.join(where), page


def auction_sql(params, detail=False):
    values, where, page = filters(params, detail)
    tooltip_columns = ''.join(',MAX(t.'+field+') AS '+field for field in ITEM_TOOLTIP_FIELDS)
    grouped = f'''SELECT i.itemEntry AS id,MAX(t.name) AS name,MAX(t.Quality) AS quality,
MAX(t.displayid) AS displayid,MAX(t.ItemLevel) AS level,MAX(t.RequiredLevel) AS required_level,
MAX(t.class) AS category,MAX(t.subclass) AS subclass,MAX(t.InventoryType) AS slot,
MAX(t.description) AS description,MAX(t.SellPrice) AS sell_price,
MAX(t.RequiredSkillRank) AS skill_rank,MAX(t.RequiredSkill) AS required_skill,
COUNT(*) AS auctions,SUM(i.count) AS quantity,
MIN(CASE WHEN a.buyoutprice>0 THEN a.buyoutprice/i.count END) AS unit_price,
MAX(CASE WHEN a.buyoutprice>0 THEN a.buyoutprice/i.count END) AS max_price,
MIN(GREATEST(a.startbid,a.lastbid)/i.count) AS bid_price{tooltip_columns}
{JOIN} WHERE {where} GROUP BY i.itemEntry'''
    totals = f'''SELECT JSON_OBJECT('kind','totals','items',COUNT(DISTINCT i.itemEntry),
'auctions',COUNT(*),'quantity',COALESCE(SUM(i.count),0)) {JOIN} WHERE {where};'''
    fields = ','.join(f"'{f}',g.{f}" for f in ('id','name','quality','displayid','level','required_level','category','subclass','slot','description','sell_price','skill_rank','required_skill','auctions','quantity','unit_price','max_price','bid_price',*ITEM_TOOLTIP_FIELDS))
    sql = PREFIX + totals + f"\nSELECT JSON_OBJECT('kind','item',{fields}) FROM ({grouped}) g ORDER BY {SORTS.get(values.get('sort'), SORTS['name'])},id LIMIT {1 if detail else 60} OFFSET {0 if detail else (page-1)*60};\n"
    if detail:
        sql += f'''SELECT JSON_OBJECT('kind','listing','id',a.id,'house',a.houseid,
'quantity',i.count,'buyout',a.buyoutprice,'bid',GREATEST(a.startbid,a.lastbid),
'unit_price',IF(a.buyoutprice>0,a.buyoutprice/i.count,NULL),'expires',a.time,
'seller',COALESCE(c.name,'Unknown seller'),'random_property',i.randomPropertyId,
'enchantments',i.enchantments)
{JOIN} LEFT JOIN acore_characters.characters c ON c.guid=a.itemowner
WHERE {where} ORDER BY a.buyoutprice=0,a.buyoutprice/i.count,a.id LIMIT 60 OFFSET {(page-1)*60};
SELECT JSON_OBJECT('kind','price','unit_price',p.unit_price,'quantity',p.quantity,'auctions',p.auctions)
FROM (SELECT a.buyoutprice/i.count AS unit_price,SUM(i.count) AS quantity,COUNT(*) AS auctions
{JOIN} WHERE {where} AND a.buyoutprice>0 GROUP BY unit_price
ORDER BY unit_price LIMIT 201) p;
'''
    return sql + 'COMMIT;\n'


class AuctionProvider:
    def __init__(self, root=ROOT, reader=read_inventory_sql):
        self.reader = reader
        try:
            self.metadata = json.loads((root / 'assets' / 'item-metadata.json').read_text())
        except (OSError, ValueError):
            self.metadata = {}
        self.lock = threading.Lock()
        self.cached = {}

    def get(self, params, detail=False):
        sql = auction_sql(params, detail)
        key = (sql, detail)
        with self.lock:
            cached = self.cached.get(key)
            if cached and time.monotonic() - cached[0] < 10:
                return cached[1]
            try:
                rows = self.reader(sql)
            except DatabaseError as exc:
                raise DatabaseError('Cannot read auctions. Check Docker access and the AzerothCore auction tables.') from exc
            totals = next((r for r in rows if r['kind'] == 'totals'), None)
            if totals is None:
                raise DatabaseError('The auction database returned an unexpected snapshot.')
            items = [dict(r) for r in rows if r['kind'] == 'item']
            for item in items:
                item['icon'] = self.metadata.get('icons', {}).get(str(item['displayid']))
            result = {'items': items, 'totals': totals, 'page': int(params.get('page', ['1'])[0]),
                      'page_size': 60, 'refreshed_at': datetime.now(timezone.utc).isoformat()}
            if detail:
                result['listings'] = [dict(r) for r in rows if r['kind'] == 'listing']
                prices = [dict(r) for r in rows if r['kind'] == 'price']
                result['prices_truncated'] = len(prices) > 200
                result['prices'] = prices[:200]
            if len(self.cached) >= 32:
                self.cached.pop(next(iter(self.cached)))
            self.cached[key] = (time.monotonic(), result)
            return result
