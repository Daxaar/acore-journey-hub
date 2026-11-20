"""Read-only saved inboxes. Merely viewing mail never changes mail flags or attachments."""
from armory import read_inventory_sql
from mysql_access import DatabaseError
from transactions import PREFIX

PAGE_SIZE=7
MAIL_JOIN="""FROM acore_characters.mail m
LEFT JOIN acore_characters.characters sender ON m.messageType=0 AND sender.guid=m.sender
LEFT JOIN acore_world.creature_template npc ON m.messageType=3 AND npc.entry=m.sender
LEFT JOIN acore_world.item_template auction_item ON m.messageType=2 AND auction_item.entry=CAST(SUBSTRING_INDEX(m.subject,':',1) AS UNSIGNED)
"""

def number(value,label):
    try:result=int(value)
    except (ValueError,TypeError):raise ValueError('Choose a valid '+label+'.')
    if not 1<=result<=4294967295:raise ValueError('Choose a valid '+label+'.')
    return result

def mailbox_sql(params):
    if set(params)-{'receiver','page','id'} or any(len(v)!=1 for v in params.values()):
        raise ValueError('Provide one value per mailbox filter.')
    receiver=number(params.get('receiver',['0'])[0],'character')
    page=number(params.get('page',['1'])[0],'page')
    if page>10000:raise ValueError('Choose a page up to 10000.')
    where=f'm.receiver={receiver} AND m.expire_time>UNIX_TIMESTAMP()'
    if params.get('id'):
        where+=f" AND m.id={number(params['id'][0],'message')}"
    selection=f"SELECT m.id FROM acore_characters.mail m WHERE {where} ORDER BY m.id DESC LIMIT {1 if params.get('id') else PAGE_SIZE} OFFSET {0 if params.get('id') else (page-1)*PAGE_SIZE}"
    body=",'body',LEFT(COALESCE(m.body,''),64000),'body_truncated',CHAR_LENGTH(COALESCE(m.body,''))>64000" if params.get('id') else ''
    return PREFIX+f"""
SELECT JSON_OBJECT('kind','mail_totals','count',COUNT(*),'unread',COALESCE(SUM((checked&1)=0),0))
FROM acore_characters.mail WHERE receiver={receiver} AND expire_time>UNIX_TIMESTAMP();
SELECT JSON_OBJECT('kind','mail','id',m.id,'receiver',m.receiver,'sender_guid',m.sender,
'sender_type',m.messageType,'sender',CASE WHEN m.messageType=2 THEN 'Auction House'
WHEN m.messageType=3 THEN COALESCE(npc.name,CONCAT('Creature #',m.sender))
WHEN m.sender=0 THEN 'System' ELSE COALESCE(sender.name,CONCAT('Sender #',m.sender)) END,
'subject',m.subject,'auction_item',auction_item.name,'template_id',m.mailTemplateId,'money',m.money,'cod',m.cod,
'deliver_time',m.deliver_time,'expire_time',m.expire_time,'read',(m.checked&1)>0{body})
{MAIL_JOIN} JOIN ({selection}) selected ON selected.id=m.id ORDER BY m.id DESC;
SELECT JSON_OBJECT('kind','attachment','mail_id',mi.mail_id,'id',i.itemEntry,'name',t.name,
'quantity',i.count,'quality',t.Quality,'displayid',t.displayid)
FROM acore_characters.mail_items mi JOIN ({selection}) selected ON selected.id=mi.mail_id
JOIN acore_characters.item_instance i ON i.guid=mi.item_guid
LEFT JOIN acore_world.item_template t ON t.entry=i.itemEntry
ORDER BY mi.mail_id,mi.item_guid;
COMMIT;
"""

class MailboxProvider:
    def __init__(self,icons=None,reader=read_inventory_sql):
        self.icons=icons or {}
        self.reader=reader

    def characters(self,names=None,q=''):
        if len(q)>100 or any(ord(c)<32 or 0xD800<=ord(c)<=0xDFFF for c in q):
            raise ValueError('Search with up to 100 printable characters.')
        if names is not None:
            if not names or any(not n.isascii() or not n.isalpha() for n in names):raise ValueError('Choose a valid group.')
            condition='c.name IN ('+','.join("'"+n+"'" for n in names)+')'
        else:
            condition='1=1' if q.strip() else 'EXISTS(SELECT 1 FROM acore_characters.mail WHERE receiver=c.guid AND expire_time>UNIX_TIMESTAMP())'
        if q.strip():
            literal='CONVERT(0x'+q.strip().encode().hex()+' USING utf8mb4)'
            condition+=f' AND LOCATE({literal},c.name)>0'
        rows=self.reader(PREFIX+f"""
SELECT JSON_OBJECT('guid',c.guid,'name',c.name,'level',c.level,'class',c.class,
'count',(SELECT COUNT(*) FROM acore_characters.mail WHERE receiver=c.guid AND expire_time>UNIX_TIMESTAMP()))
FROM acore_characters.characters c WHERE {condition} ORDER BY c.name LIMIT 500;
COMMIT;
""")
        return rows

    def get(self,params):
        try:rows=self.reader(mailbox_sql(params))
        except DatabaseError as error:raise DatabaseError('Mailbox unavailable. Check the realm database connection.') from error
        mails=[dict(row) for row in rows if row['kind']=='mail']
        for mail in mails:
            mail['attachments']=[]
            for row in rows:
                if row['kind']=='attachment' and row['mail_id']==mail['id']:
                    attachment=dict(row)
                    attachment['icon']=self.icons.get(str(row.get('displayid')))
                    mail['attachments'].append(attachment)
        return {'messages':mails,'totals':next((row for row in rows if row['kind']=='mail_totals'),{'count':0,'unread':0}),
                'page':int(params.get('page',['1'])[0]),'page_size':PAGE_SIZE}
