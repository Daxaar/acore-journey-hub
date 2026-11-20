"""Read-only, paginated access to the module's append-only observations."""
from datetime import datetime, timezone
import json
import subprocess
import tempfile
from functools import lru_cache
from connection import mysql_command, database_sql, database_environment
from armory import read_inventory_sql
from mysql_access import DatabaseError

KINDS = ('loot','loot_money','mail_sent_observed','listing_observed','sale_settlement_observed','expiration_observed','removal_observed','vendor_purchase','vendor_sale_observed')
PREFIX = """SET SESSION time_zone = "+00:00";
SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
"""
JOIN = """FROM acore_characters.transaction_journal j
LEFT JOIN acore_characters.characters c ON c.guid=j.actor_guid
LEFT JOIN acore_characters.characters other ON other.guid=j.counterparty_guid
LEFT JOIN acore_world.item_template t ON t.entry=j.item_id"""

@lru_cache(maxsize=1)
def transaction_locations():
    """Client-era names and dungeon classifications from the existing server DBC source."""
    from prepare_quest_assets import read_dbc
    try:
        maps,map_text=read_dbc('Map')
        areas,area_text=read_dbc('AreaTable')
        dungeons=[{'id':row[0],'name':map_text(row[5])} for row in maps if row[2]==1 and map_text(row[5])]
        zones=sorted({area_text(row[11]) for row in areas if row[2]==0 and area_text(row[11])},key=str.casefold)
        return {'dungeons':sorted(dungeons,key=lambda row:row['name'].casefold()),'zones':zones}
    except (OSError,ValueError) as error:
        raise DatabaseError('Location suggestions are unavailable. Check access to the server DBC files.') from error


EVENT_SORT = """CASE j.event_kind
WHEN 'loot' THEN 'Item loot' WHEN 'loot_money' THEN 'Money loot'
WHEN 'listing_observed' THEN 'AH listing'
WHEN 'sale_settlement_observed' THEN 'Sale settlement observed'
WHEN 'expiration_observed' THEN 'Expiration observed'
WHEN 'removal_observed' THEN 'Removal observed'
WHEN 'vendor_purchase' THEN 'Vendor purchase'
WHEN 'vendor_sale_observed' THEN 'Vendor sale observed'
WHEN 'mail_sent_observed' THEN 'Mail sent observed' ELSE j.event_kind END"""
SORT_COLUMNS = {
    'time': ('j.recorded_at',),
    'character': ('c.name','other.name'),
    'event': (EVENT_SORT,),
    'source': ('j.source_name','j.zone_name'),
    'item': ("""COALESCE(t.name,
        (SELECT MIN(sort_item.name)
         FROM JSON_TABLE(COALESCE(j.mail_items,JSON_ARRAY()),'$[*]' COLUMNS(item_id INT PATH '$.item_id')) sort_attachment
         LEFT JOIN acore_world.item_template sort_item ON sort_item.entry=sort_attachment.item_id),
        CASE WHEN j.event_kind='loot_money' THEN 'Money' END,j.mail_subject)""",),
    'quantity': ("CASE WHEN j.event_kind!='loot_money' THEN j.quantity END",),
    'vendor': ("CASE WHEN j.event_kind='loot' THEN j.quantity*COALESCE(t.SellPrice,0) END",),
    'price': ("""CASE j.event_kind
        WHEN 'listing_observed' THEN j.start_bid
        WHEN 'sale_settlement_observed' THEN j.proceeds
        WHEN 'vendor_purchase' THEN j.gross
        WHEN 'vendor_sale_observed' THEN j.proceeds
        WHEN 'loot_money' THEN j.gross
        WHEN 'mail_sent_observed' THEN j.mail_postage END""",),
    'listing': ('NULLIF(j.auction_id,0)',),
}

def transaction_sql(params, names=None, export=False):
    allowed={'page','kind','q','from','to','character','group','source','zone','dungeon','sort','direction'}
    if set(params)-allowed or any(len(v)!=1 for v in params.values()):
        raise ValueError('Provide one value per transaction filter.')
    values={k:v[0] for k,v in params.items()}
    page=int(values.get('page','1'))
    if not 1<=page<=10000:raise ValueError('Choose a page from 1 to 10000.')
    sort=values.get('sort','time')
    direction=values.get('direction','desc')
    if sort not in SORT_COLUMNS or direction not in ('asc','desc'):
        raise ValueError('Choose a valid sort column and direction.')
    order=', '.join(f'{column} IS NULL ASC, {column} {direction.upper()}' for column in SORT_COLUMNS[sort])
    order+=', j.id DESC'
    where=['1=1']
    kind=values.get('kind','')
    if kind:
        if kind not in KINDS:raise ValueError('Choose a known event type.')
        where.append("j.event_kind='"+kind+"'")
    for key,op in [('from','>='),('to','<')]:
        if values.get(key):
            try:
                value=datetime.fromisoformat(values[key])
            except ValueError:
                raise ValueError('Choose a valid date and time.')
            where.append("j.recorded_at"+op+"'"+value.strftime('%Y-%m-%d %H:%M:%S')+"'")
    if values.get('from') and values.get('to') and datetime.fromisoformat(values['from'])>=datetime.fromisoformat(values['to']):
        raise ValueError('End time must follow start time.')
    character=values.get('character','')
    if character:
        if not character.isascii() or not character.isdigit() or not 0<int(character)<=4294967295:
            raise ValueError('Choose a valid character.')
        where.append(f'(j.actor_guid={int(character)} OR j.counterparty_guid={int(character)})')
    if names is not None:
        if not names or any(not n.isascii() or not n.isalpha() for n in names):
            raise ValueError('Choose a valid group.')
        literal=','.join("'"+n+"'" for n in names)
        where.append(f'(c.name IN ({literal}) OR other.name IN ({literal}))')
    q=values.get('q','').strip()
    if len(q)>100 or any(ord(c)<32 or 0xD800<=ord(c)<=0xDFFF for c in q):
        raise ValueError('Search with up to 100 printable characters.')
    if q:
        term='CONVERT(0x'+q.encode().hex()+' USING utf8mb4)'
        numeric=q.isascii() and q.isdigit() and len(q)<=10
        item_match=f' OR j.item_id={int(q)}' if numeric else ''
        attachment_match=f' OR attachment.item_id={int(q)}' if numeric else ''
        where.append(f'''(LOCATE({term},t.name)>0 OR LOCATE({term},j.mail_subject)>0{item_match}
OR EXISTS(SELECT 1 FROM JSON_TABLE(COALESCE(j.mail_items,JSON_ARRAY()),'$[*]'
COLUMNS(item_id INT PATH '$.item_id')) attachment
LEFT JOIN acore_world.item_template mail_item ON mail_item.entry=attachment.item_id
WHERE LOCATE({term},mail_item.name)>0{attachment_match}))''')
    for key,column,id_column in [('source','source_name','source_entry'),('zone','zone_name','zone_id')]:
        term=values.get(key,'').strip()
        if len(term)>100 or any(ord(c)<32 or 0xD800<=ord(c)<=0xDFFF for c in term):
            raise ValueError('Search with up to 100 printable characters.')
        if term:
            literal='CONVERT(0x'+term.encode().hex()+' USING utf8mb4)'
            where.append(f'(LOCATE({literal},j.{column})>0'+(f' OR j.{id_column}={int(term)}' if term.isascii() and term.isdigit() and len(term)<=10 else '')+')')
    dungeon=values.get('dungeon','').strip()
    if len(dungeon)>100 or any(ord(c)<32 or 0xD800<=ord(c)<=0xDFFF for c in dungeon):
        raise ValueError('Search with up to 100 printable characters.')
    if dungeon:
        matches=[row['id'] for row in transaction_locations()['dungeons']
                 if dungeon.casefold() in row['name'].casefold() or dungeon==str(row['id'])]
        where.append('j.map_id IN ('+','.join(map(str,matches))+')' if matches else '1=0')
    sender_scope=f'j.actor_guid={int(character)}' if character else '1=1'
    if names is not None:
        sender_scope+=' AND c.name IN ('+','.join("'"+name+"'" for name in names)+')'
    condition=' AND '.join(where)
    fields=('id','event_uuid','event_kind','listing_key','actor_guid','counterparty_guid','item_id',
            'quantity','auction_id','house_id','start_bid','buyout','gross','deposit','fee','proceeds',
            'actor_ahbot','counterparty_ahbot','source_type','source_entry','source_guid','source_name',
            'map_id','map_name','zone_id','zone_name','area_id','area_name','mail_postage','mail_money','mail_cod','mail_subject')
    columns=','.join("'"+f+"',j."+f for f in fields)
    pagination='' if export else f' LIMIT 100 OFFSET {(page-1)*100}'
    return PREFIX+f"""
SELECT JSON_OBJECT('kind','totals','events',COUNT(*),
'mail_postage',COALESCE(SUM(IF(j.event_kind='mail_sent_observed' AND {sender_scope},j.mail_postage,0)),0),
'mail_money',COALESCE(SUM(IF(j.event_kind='mail_sent_observed' AND {sender_scope},j.mail_money,0)),0),
'loot_copper',COALESCE(SUM(IF(j.event_kind='loot_money',j.gross,0)),0),
'loot_quantity',COALESCE(SUM(IF(j.event_kind='loot',j.quantity,0)),0),
'loot_vendor_value',COALESCE(SUM(IF(j.event_kind='loot',j.quantity*COALESCE(t.SellPrice,0),0)),0),
'settlement_proceeds',COALESCE(SUM(IF(j.event_kind='sale_settlement_observed',j.proceeds,0)),0))
{JOIN} WHERE {condition};
SELECT JSON_OBJECT({columns},'recorded_at',DATE_FORMAT(j.recorded_at,'%Y-%m-%dT%H:%i:%sZ'),
'mail_items',(SELECT JSON_ARRAYAGG(JSON_OBJECT('id',a.item_id,'quantity',a.quantity,'name',mt.name,'displayid',mt.displayid))
FROM JSON_TABLE(COALESCE(j.mail_items,JSON_ARRAY()),'$[*]' COLUMNS(item_id INT PATH '$.item_id',quantity INT PATH '$.quantity')) a
LEFT JOIN acore_world.item_template mt ON mt.entry=a.item_id),
'character',c.name,'counterparty',other.name,'item',t.name,'displayid',t.displayid,'vendor_sell_price',COALESCE(t.SellPrice,0))
{JOIN} WHERE {condition} ORDER BY {order}{pagination};
COMMIT;
"""

def get_transactions(params,names=None,reader=read_inventory_sql,icons=None):
    try:
        rows=reader(transaction_sql(params,names))
    except DatabaseError as exc:
        raise DatabaseError('Transaction history is unavailable. Check the recorder table and realm connection.') from exc
    events=[dict(row) for row in rows[1:]]
    for event in events:
        event['icon']=(icons or {}).get(str(event.get('displayid')))
        for attachment in event.get('mail_items') or []:
            attachment['icon']=(icons or {}).get(str(attachment.get('displayid')))
    return {'totals':rows[0],'events':events,'page':int(params.get('page',['1'])[0]),'page_size':100}


def export_transactions(params,names=None,icons=None):
    """Build a download from one consistent read-only snapshot, without a page-size cap."""
    sql=transaction_sql(params,names,export=True)
    output=tempfile.TemporaryFile(mode='w+b')
    try:
        with tempfile.TemporaryFile(mode='w+t',encoding='utf-8') as raw:
            result=subprocess.run(mysql_command(xml=False),env=database_environment(),
                input=database_sql(sql),stdout=raw,stderr=subprocess.PIPE,text=True,encoding='utf-8',timeout=60)
            if result.returncode:raise DatabaseError('Cannot export transaction history. Try again or narrow the filters.')
            raw.seek(0)
            if json.loads(raw.readline())!={'kind':'meta','read_only':1}:
                raise DatabaseError('Read-only export could not be confirmed.')
            totals=json.loads(raw.readline())
            if totals.get('kind')!='totals':raise DatabaseError('Unexpected export response.')
            metadata={'schema':1,'exported_at':datetime.now(timezone.utc).isoformat(),
                      'filters':{key:value[0] for key,value in params.items() if key!='page'},
                      'totals':totals}
            output.write((json.dumps(metadata)[:-1]+',"events":[').encode())
            count=0
            for line in raw:
                if not line.strip():continue
                event=json.loads(line)
                event['icon']=(icons or {}).get(str(event.get('displayid')))
                for attachment in event.get('mail_items') or []:
                    attachment['icon']=(icons or {}).get(str(attachment.get('displayid')))
                if count:output.write(b',')
                output.write(json.dumps(event).encode())
                count+=1
            if count!=int(totals['events']):
                raise DatabaseError('Export snapshot is incomplete. Please try again.')
            output.write(b']}')
        output.seek(0)
        return output
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        output.close()
        raise DatabaseError('Transaction export failed. Try again or narrow the filters.') from exc
    except BaseException:
        output.close()
        raise
