"""Saved character inventory provider; deliberately independent of quest-source adapters."""
from connection import mysql_command, database_sql, database_environment
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import threading
import time
import urllib.request

from observed_changes import ObservedChanges
from mysql_access import CONTAINER, DatabaseError, name_filter

ROOT = Path(__file__).resolve().parent
ITEM_TOOLTIP_FIELDS = ['armor','block','delay','dmg_min1','dmg_max1','ContainerSlots','MaxDurability','bonding','AllowableClass','AllowableRace'] + [field+str(i) for i in range(1,11) for field in ('stat_type','stat_value')]

EQUIPMENT = ('Head', 'Neck', 'Shoulders', 'Shirt', 'Chest', 'Waist', 'Legs', 'Feet', 'Wrists',
             'Hands', 'Finger 1', 'Finger 2', 'Trinket 1', 'Trinket 2', 'Back', 'Main hand', 'Off hand',
             'Ranged', 'Tabard')


def armory_sql(name):
    selected = name_filter('c', [name])
    character = ['guid', 'name', 'race', 'class', 'gender', 'level', 'skin', 'face', 'hairStyle',
                 'hairColor', 'facialStyle', 'health', 'money']
    template = ['name', 'displayid', 'Quality', 'InventoryType', 'ItemLevel', 'RequiredLevel',
                'ContainerSlots', 'armor', 'MaxDurability', 'description', 'delay', 'dmg_min1', 'dmg_max1']
    template += [field + str(i) for i in range(1, 11) for field in ('stat_type', 'stat_value')]
    fields = ["'kind','item'", "'bag',v.bag", "'slot',v.slot", "'guid',v.item",
              "'entry',i.itemEntry", "'owner',i.owner_guid", "'count',i.count", "'durability',i.durability",
              "'randomPropertyId',i.randomPropertyId", "'enchantments',i.enchantments"]
    fields += [f"'{field}',t.{field}" for field in template]
    guild_fields = [field.replace("'kind','item'", "'kind','guild_item'").replace("'bag',v.bag", "'bag',v.TabId").replace("'slot',v.slot", "'slot',v.SlotId").replace("'guid',v.item", "'guid',v.item_guid") for field in fields]
    guild_join = "FROM acore_characters.characters c JOIN acore_characters.guild_member gm ON gm.guid=c.guid JOIN acore_characters.guild g ON g.guildid=gm.guildid"
    return f"""
SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
SELECT JSON_OBJECT('kind','character',{','.join(repr(f)+',c.'+f for f in character)})
FROM acore_characters.characters c WHERE {selected};
SELECT JSON_OBJECT({','.join(fields)})
FROM acore_characters.characters c JOIN acore_characters.character_inventory v ON v.guid=c.guid
LEFT JOIN acore_characters.item_instance i ON i.guid=v.item
LEFT JOIN acore_world.item_template t ON t.entry=i.itemEntry
WHERE {selected} ORDER BY v.bag,v.slot LIMIT 1001;
SELECT JSON_OBJECT('kind','guild','id',g.guildid,'name',g.name,'money',g.BankMoney)
{guild_join} WHERE {selected};
SELECT JSON_OBJECT('kind','guild_tab','id',b.TabId,'name',b.TabName)
{guild_join} JOIN acore_characters.guild_bank_tab b ON b.guildid=g.guildid
WHERE {selected} ORDER BY b.TabId LIMIT 7;
SELECT JSON_OBJECT({','.join(guild_fields)})
{guild_join} JOIN acore_characters.guild_bank_item v ON v.guildid=g.guildid
LEFT JOIN acore_characters.item_instance i ON i.guid=v.item_guid
LEFT JOIN acore_world.item_template t ON t.entry=i.itemEntry
WHERE {selected} ORDER BY v.TabId,v.SlotId LIMIT 589;
COMMIT;
"""


def read_inventory(name):
    return read_inventory_sql(armory_sql(name))


def read_inventory_sql(sql, timeout=12):
    command = mysql_command(xml=False)
    try:
        result = subprocess.run(command, env=database_environment(), input=database_sql(sql), capture_output=True, text=True, encoding='utf-8', timeout=timeout)
        if result.returncode or len(result.stdout) > 4000000:
            raise ValueError('Query failed')
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        if not rows or rows[0] != {'kind': 'meta', 'read_only': 1}:
            raise ValueError('Read-only session not confirmed')
        return rows[1:]
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise DatabaseError('Cannot read saved inventory. Check Docker access and the Playerbots database.') from exc


def bag_space_sql(names):
    if not isinstance(names, (list, tuple)) or not 1 <= len(names) <= 10:
        raise ValueError('Choose between 1 and 10 character names.')
    selected = name_filter('c', names)
    return f"""SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
SELECT JSON_OBJECT('kind','space','name',c.name,'capacity',16 + COALESCE((
 SELECT SUM(CASE WHEN t.ContainerSlots BETWEEN 0 AND 64 THEN t.ContainerSlots ELSE 0 END)
 FROM acore_characters.character_inventory bv
 LEFT JOIN acore_characters.item_instance i ON i.guid=bv.item
 LEFT JOIN acore_world.item_template t ON t.entry=i.itemEntry
 WHERE bv.guid=c.guid AND bv.bag=0 AND bv.slot BETWEEN 19 AND 22),0),
 'occupied',COUNT(DISTINCT CASE WHEN (v.bag=0 AND v.slot BETWEEN 23 AND 38)
 OR (b.item IS NOT NULL AND v.slot<bt.ContainerSlots AND bt.ContainerSlots BETWEEN 0 AND 64)
 THEN CONCAT(v.bag,':',v.slot) END))
FROM acore_characters.characters c
LEFT JOIN acore_characters.character_inventory v ON v.guid=c.guid
LEFT JOIN acore_characters.character_inventory b ON b.guid=c.guid AND b.item=v.bag AND b.bag=0 AND b.slot BETWEEN 19 AND 22
LEFT JOIN acore_characters.item_instance bi ON bi.guid=b.item
LEFT JOIN acore_world.item_template bt ON bt.entry=bi.itemEntry
WHERE {selected} GROUP BY c.guid,c.name LIMIT 10;
COMMIT;
"""


def build_inventory(rows, metadata):
    character = next((r for r in rows if r['kind'] == 'character'), None)
    if not character:
        raise LookupError('No saved character found with that name.')
    items = [dict(r) for r in rows if r['kind'] == 'item']
    guild_items = [dict(r) for r in rows if r['kind'] == 'guild_item']
    guild = next((dict(r) for r in rows if r['kind'] == 'guild'), None)
    guild_tabs = [r for r in rows if r['kind'] == 'guild_tab']
    if len(guild_items) >= 589 or len(guild_tabs) > 6:
        raise DatabaseError('Guild bank exceeds the dashboard safety limit; no partial inventory was displayed.')
    if len(items) >= 1001:
        raise DatabaseError('Inventory exceeds the dashboard safety limit; no partial inventory was displayed.')
    issues = []
    for item in items + guild_items:
        if (item['kind'] == 'item' and item.get('owner') != character['guid']) or not item.get('name'):
            issues.append('An inventory record has missing template data or an unexpected owner.')
        item['name'] = item.get('name') or f"Unknown item #{item.get('entry') or item['guid']}"
        item['icon'] = metadata.get('icons', {}).get(str(item.get('displayid')))
        random = item.get('randomPropertyId') or 0
        suffix = metadata.get('properties' if random > 0 else 'suffixes', {}).get(str(abs(random)))
        if random and suffix:
            item['name'] += ' ' + suffix
        enchants = (item.get('enchantments') or '').split()
        item['enchant_labels'] = []
        for offset in range(0, len(enchants), 3):
            if enchants[offset].isdigit() and int(enchants[offset]):
                eid = enchants[offset]
                item['enchant_labels'].append(metadata.get('enchants', {}).get(eid) or f'Enchantment #{eid}')
    positions = {}
    for item in items:
        key = (item['bag'], item['slot'])
        if key in positions:
            issues.append('Duplicate inventory position detected.')
        positions[key] = item
    used = set()

    def take(bag, slot):
        value = positions.get((bag, slot))
        if value:
            used.add(value['guid'])
        return value

    equipment = [{'slot': i, 'label': label, 'item': take(0, i)} for i, label in enumerate(EQUIPMENT)]
    bags = [{'id': 'backpack', 'name': 'Backpack', 'item': None, 'capacity': 16,
             'slots': [take(0, i) for i in range(23, 39)]}]
    for slot in range(19, 23):
        bag = take(0, slot)
        capacity = (bag.get('ContainerSlots') or 0) if bag else 0
        if not 0 <= capacity <= 64:
            issues.append('A bag capacity is outside the supported range.')
            capacity = 0
        bags.append({'id': f'bag-{slot}', 'name': bag['name'] if bag else 'No bag equipped', 'item': bag,
                     'capacity': capacity, 'slots': [take(bag['guid'], i) for i in range(capacity)] if bag else []})
    bank = [{'id': 'bank-main', 'name': 'Bank', 'item': None, 'capacity': 28,
             'slots': [take(0, i) for i in range(39, 67)]}]
    for slot in range(67, 74):
        bag = take(0, slot)
        capacity = (bag.get('ContainerSlots') or 0) if bag else 0
        if not 0 <= capacity <= 64:
            issues.append('A bank bag capacity is outside the supported range.')
            capacity = 0
        bank.append({'id': f'bank-bag-{slot}', 'name': bag['name'] if bag else 'No bank bag equipped',
                     'item': bag, 'capacity': capacity,
                     'slots': [take(bag['guid'], i) for i in range(capacity)] if bag else []})
    bank_guids = {i['guid'] for i in items if i['bag'] == 0 and 67 <= i['slot'] <= 73}
    stored = [i for i in items if (i['bag'] == 0 and 39 <= i['slot'] <= 149) or i['bag'] in bank_guids]
    guild_bags = []
    guild_positions = {}
    for item in guild_items:
        key = (item['bag'], item['slot'])
        if key in guild_positions:
            issues.append('Duplicate guild bank position detected.')
        guild_positions[key] = item
    tab_ids = {tab['id'] for tab in guild_tabs}
    if any(i['bag'] not in tab_ids or not 0 <= i['slot'] < 98 for i in guild_items):
        issues.append('Some guild bank records could not be placed.')
    for tab in guild_tabs:
        guild_bags.append({'id': f"guild-tab-{tab['id']}", 'name': tab['name'] or f"Tab {tab['id'] + 1}",
                           'item': None, 'capacity': 98,
                           'slots': [guild_positions.get((tab['id'], i)) for i in range(98)]})
    stored_guids = {i['guid'] for i in stored}
    unplaced = len([i for i in items if i['guid'] not in used | stored_guids])
    if unplaced:
        issues.append(f'{unplaced} records could not be placed in the carried inventory.')
    for bag in bags + bank + guild_bags:
        bag['occupied'] = sum(i is not None for i in bag['slots'])
    return {'character': character, 'equipment': equipment, 'bags': bags,
            'bank': bank, 'guild': guild, 'guild_bags': guild_bags,
            'capacity': sum(b['capacity'] for b in bags), 'occupied': sum(b['occupied'] for b in bags),
            'stored_records': len(stored), 'warnings': list(dict.fromkeys(issues)),
            'source': 'MySQL saved inventory', 'refreshed_at': datetime.now(timezone.utc).isoformat()}


class ArmoryProvider:
    def __init__(self, root=ROOT, reader=read_inventory):
        self.root, self.reader = root, reader
        try:
            self.metadata = json.loads((root / 'assets' / 'item-metadata.json').read_text())
        except (OSError, ValueError):
            self.metadata = {}
        self.icon_names = set(self.metadata.get('icons', {}).values())
        try:
            self.icon_names.update(json.loads((root / 'assets' / 'profession-metadata.json').read_text()).get('icon_names',[]))
        except (OSError,ValueError):pass
        self.lock = threading.Lock()
        self.icon_lock = threading.BoundedSemaphore(4)
        self.failed_icons = {}
        self.cached = {}
        self.space_cached = {}
        self.changes = ObservedChanges()

    def get(self, name):
        name_filter('c', [name])
        key = name.lower()
        with self.lock:
            cached = self.cached.get(key)
            if cached and time.monotonic() - cached[0] < 2:
                return cached[1]
            data = build_inventory(self.reader(name), self.metadata)
            data['changes'] = self.changes.observe(key, {k:v for k,v in data.items() if k != 'refreshed_at'}, data['refreshed_at'])
            if len(self.cached) >= 64:
                self.cached.pop(next(iter(self.cached)))
            self.cached[key] = (time.monotonic(), data)
            return data

    def bag_space(self, names, reader=read_inventory_sql):
        sql = bag_space_sql(names)
        key = tuple(n.lower() for n in names)
        with self.lock:
            cached = self.space_cached.get(key)
            if cached and time.monotonic() - cached[0] < 2:
                return cached[1]
            rows = reader(sql)
            found = {r['name'].lower():r for r in rows if r['kind']=='space'}
            characters = []
            for name in names:
                row = found.get(name.lower())
                characters.append({'name':row['name'] if row else name, 'found':row is not None,
                    'free':max(0,int(row['capacity'])-int(row['occupied'])) if row else None})
            result = {'characters':characters, 'refreshed_at':datetime.now(timezone.utc).isoformat()}
            if len(self.space_cached)>=64: self.space_cached.pop(next(iter(self.space_cached)))
            self.space_cached[key] = (time.monotonic(),result)
            return result

    def icon(self, name):
        if not re.fullmatch(r'[a-z0-9_]{1,100}', name) or name not in self.icon_names:
            raise LookupError('Unknown icon')
        destination = self.root / 'assets' / 'icons' / (name + '.jpg')
        with self.icon_lock:
            if destination.is_file():
                return destination.read_bytes()
            if time.monotonic() - self.failed_icons.get(name, -1000) < 60:
                raise LookupError('Icon unavailable')
            try:
                request = urllib.request.Request('https://wow.zamimg.com/images/wow/icons/large/' + name + '.jpg',
                                                 headers={'User-Agent': 'CharacterHub/1.0'})
                with urllib.request.urlopen(request, timeout=4) as response:
                    data = response.read(200001)
                if len(data) > 200000 or not data.startswith(b'\xff\xd8\xff'):
                    raise ValueError('Invalid icon')
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(f'.{threading.get_ident()}.tmp')
                temporary.write_bytes(data)
                temporary.replace(destination)
                return data
            except (OSError, ValueError):
                self.failed_icons[name] = time.monotonic()
                raise LookupError('Icon unavailable') from None
