"""Independent local adventurers' stories and screenshots; no game database access."""
import base64
import binascii
from datetime import date, datetime, timezone
import re
import sqlite3
import struct
import threading
import uuid
from groups import validate_group

CATEGORIES=('Adventures','Guild Business','Notable Characters','Disasters')
MAX_IMAGE=5*1024*1024
MAX_IMAGES=4
MAX_REQUEST=29*1024*1024


class JournalConflict(ValueError):pass


def text(value,label,limit,required=False):
    if not isinstance(value,str) or len(value)>limit or any((ord(c)<32 and c not in '\n\r\t') or 0xD800<=ord(c)<=0xDFFF for c in value):
        raise ValueError(f'{label}: use up to {limit:,} characters.')
    value=value.strip()
    if required and not value:raise ValueError(label+' is required.')
    return value


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):raise ValueError('Invalid journal reference.')
    return value


def character_name(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z]{2,12}',value.strip()):
        raise ValueError('Character tags must contain 2–12 letters.')
    return value.strip().capitalize()


def character_tags(value):
    if not isinstance(value,list) or len(value)>32:raise ValueError('Use up to 32 character tags.')
    return list(dict.fromkeys(character_name(name) for name in value))


def group_tags(value):
    if not isinstance(value,list) or len(value)>32:raise ValueError('Use up to 32 group tags.')
    result=[];seen=set()
    for group in value:
        if not isinstance(group,dict) or not isinstance(group.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9-]{1,40}',group['id']) or group['id'] in seen:
            raise ValueError('Invalid or duplicate journal group tag.')
        seen.add(group['id'])
        result.append({'id':group['id'],**validate_group(group.get('name'),group.get('members'))})
    return result


def person_mentioned(people,name):
    return bool(re.search(r'(?<![A-Za-z])'+re.escape(name)+r'(?![A-Za-z])',people,re.IGNORECASE))


def screenshot(value):
    if not isinstance(value,dict):raise ValueError('Invalid screenshot.')
    name=text(value.get('name'),'Screenshot name',160,True)
    encoded=value.get('data')
    if not isinstance(encoded,str) or len(encoded)>((MAX_IMAGE+2)//3)*4:raise ValueError('Each screenshot must be at most 5 MiB.')
    try:data=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error):raise ValueError('Invalid screenshot encoding.') from None
    if len(data)>MAX_IMAGE:raise ValueError('Each screenshot must be at most 5 MiB.')
    width=height=0;mime=None
    if len(data)>=33 and data.startswith(b'\x89PNG\r\n\x1a\n') and data[12:16]==b'IHDR' and data.endswith(b'IEND\xaeB`\x82'):
        width,height=struct.unpack_from('>II',data,16);mime='image/png'
    elif data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'):
        offset=2
        while offset+4<=len(data):
            if data[offset]!=255:break
            while offset<len(data) and data[offset]==255:offset+=1
            if offset>=len(data):break
            marker=data[offset];offset+=1
            if marker in (0xD8,0xD9) or 0xD0<=marker<=0xD7:continue
            if offset+2>len(data):break
            length=struct.unpack_from('>H',data,offset)[0]
            if length<2 or offset+length>len(data):break
            if marker in (0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF) and length>=8:
                height,width=struct.unpack_from('>HH',data,offset+3);mime='image/jpeg';break
            if marker==0xDA:break
            offset+=length
    if not mime or not width or not height or width*height>40_000_000:
        raise ValueError('Use a PNG or JPEG screenshot, up to 40 megapixels.')
    return {'id':uuid.uuid4().hex,'name':name,'mime':mime,'data':data}


class JournalStore:
    def __init__(self,path=None):
        self.path=path;self.lock=threading.Lock();self._db=None

    @property
    def db(self):
        if self._db is not None:return self._db
        db=sqlite3.connect(str(self.path) if self.path else ':memory:',timeout=5,check_same_thread=False)
        try:
            db.row_factory=sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            db.create_function('journal_person',2,person_mentioned,deterministic=True)
            db.executescript('''CREATE TABLE IF NOT EXISTS entries (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, entry_date TEXT NOT NULL, date_label TEXT NOT NULL,
 category TEXT NOT NULL, location TEXT NOT NULL, people TEXT NOT NULL, story TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS journal_date ON entries(entry_date,created_at,id);
CREATE TABLE IF NOT EXISTS screenshots (
 id TEXT PRIMARY KEY, entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
 name TEXT NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS journal_character_tags (
 entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
 name TEXT NOT NULL COLLATE NOCASE, PRIMARY KEY(entry_id,name));
CREATE INDEX IF NOT EXISTS journal_character_names ON journal_character_tags(name,entry_id);
CREATE TABLE IF NOT EXISTS journal_group_tags (
 entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
 group_id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY(entry_id,group_id));
CREATE TABLE IF NOT EXISTS journal_group_members (
 entry_id TEXT NOT NULL, group_id TEXT NOT NULL, name TEXT NOT NULL COLLATE NOCASE,
 PRIMARY KEY(entry_id,group_id,name),
 FOREIGN KEY(entry_id,group_id) REFERENCES journal_group_tags(entry_id,group_id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS journal_group_character_names ON journal_group_members(name,entry_id);''')
            if self.path:self.path.chmod(0o600)
        except Exception:
            db.close();raise
        self._db=db
        return db

    def close(self):
        with self.lock:
            if self._db:self._db.close();self._db=None

    def _entry(self,entry_id):
        row=self.db.execute('SELECT * FROM entries WHERE id=?',(entry_id,)).fetchone()
        if not row:raise LookupError('Journal entry not found.')
        entry=dict(row)
        entry['screenshots']=[dict(r) for r in self.db.execute('SELECT id,name,mime FROM screenshots WHERE entry_id=? ORDER BY rowid',(entry_id,))]
        entry['character_tags']=[r[0] for r in self.db.execute('SELECT name FROM journal_character_tags WHERE entry_id=? ORDER BY rowid',(entry_id,))]
        entry['group_tags']=[{'id':r['group_id'],'name':r['name'],
            'members':[m[0] for m in self.db.execute('SELECT name FROM journal_group_members WHERE entry_id=? AND group_id=? ORDER BY rowid',(entry_id,r['group_id']))]}
            for r in self.db.execute('SELECT group_id,name FROM journal_group_tags WHERE entry_id=? ORDER BY rowid',(entry_id,))]
        return entry

    def get(self,entry_id):
        identifier(entry_id)
        with self.lock,self.db:
            self.db.execute("BEGIN")
            return self._entry(entry_id)

    def image(self,image_id):
        identifier(image_id)
        with self.lock:
            row=self.db.execute('SELECT mime,data FROM screenshots WHERE id=?',(image_id,)).fetchone()
            if not row:raise LookupError('Screenshot not found.')
            return row['mime'],row['data']

    def list(self,search='',category='',order='newest',page=0,character=''):
        search=text(search,'Search',100)
        if not isinstance(character,str):raise ValueError('Choose a character name.')
        character=character_name(character) if character.strip() else ''
        if category not in ('',*CATEGORIES) or order not in ('newest','oldest') or type(page)is not int or not 0<=page<=10000:
            raise ValueError('Choose a valid journal filter or page.')
        where=[];params=[]
        if category:where.append('category=?');params.append(category)
        if search:where.append("(instr(lower(title||' '||story||' '||location||' '||people||' '||date_label),lower(?))>0 OR EXISTS (SELECT 1 FROM journal_character_tags t WHERE t.entry_id=entries.id AND instr(lower(t.name),lower(?))>0) OR EXISTS (SELECT 1 FROM journal_group_tags t WHERE t.entry_id=entries.id AND instr(lower(t.name),lower(?))>0) OR EXISTS (SELECT 1 FROM journal_group_members t WHERE t.entry_id=entries.id AND instr(lower(t.name),lower(?))>0))");params.extend([search]*4)
        if character:
            where.append('(EXISTS (SELECT 1 FROM journal_character_tags t WHERE t.entry_id=entries.id AND t.name=? COLLATE NOCASE) OR '
                         'EXISTS (SELECT 1 FROM journal_group_members t WHERE t.entry_id=entries.id AND t.name=? COLLATE NOCASE) OR journal_person(people,?))')
            params.extend([character]*3)
        where=' WHERE '+' AND '.join(where) if where else ''
        direction='DESC' if order=='newest' else 'ASC'
        with self.lock,self.db:
            self.db.execute("BEGIN")
            total=self.db.execute('SELECT COUNT(*) FROM entries'+where,params).fetchone()[0]
            rows=self.db.execute('SELECT id,title,entry_date,date_label,category,location,people,substr(story,1,220) AS excerpt,'
                '(SELECT count(*) FROM screenshots s WHERE s.entry_id=entries.id) AS image_count FROM entries'+where+
                f' ORDER BY entry_date {direction},created_at {direction},id {direction} LIMIT 50 OFFSET ?',[*params,page*50]).fetchall()
            names=[r[0] for r in self.db.execute('SELECT name FROM journal_character_tags UNION SELECT name FROM journal_group_members ORDER BY name COLLATE NOCASE')]
            return {'characters':names,'entries':[dict(r) for r in rows],'total':total,'page':page,'page_size':50,'categories':list(CATEGORIES)}

    def save(self,payload):
        fields={key:text(payload.get(key,''),label,limit,required) for key,label,limit,required in (
            ('title','Title',160,True),('date_label','In-world date',120,False),('location','Location',120,False),
            ('people','Characters',200,False),('story','Story',30000,True))}
        tagged_characters=character_tags(payload['character_tags']) if 'character_tags' in payload else None
        tagged_groups=group_tags(payload['group_tags']) if 'group_tags' in payload else None
        day=payload.get('entry_date');category=payload.get('category')
        try:
            if not isinstance(day,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):raise ValueError()
            date.fromisoformat(day)
        except (TypeError,ValueError):raise ValueError('Choose a valid entry date.') from None
        if category not in CATEGORIES:raise ValueError('Choose a journal category.')
        fields.update(entry_date=day,category=category)
        entry_id=payload.get('id');revision=payload.get('revision')
        if entry_id is not None:identifier(entry_id)
        images=payload.get('images',[]);removed=payload.get('remove_images',[])
        if not isinstance(images,list) or len(images)>MAX_IMAGES or not isinstance(removed,list) or len(removed)>MAX_IMAGES:
            raise ValueError('Use up to four screenshots per entry.')
        removed=set(identifier(i) for i in removed)
        images=[screenshot(value) for value in images]
        now=datetime.now(timezone.utc).isoformat()
        with self.lock,self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if entry_id:
                previous=self._entry(entry_id)
                if type(revision)is not int or revision!=previous['revision']:
                    raise JournalConflict('This entry changed in another window. Reopen it before saving; your draft is still here.')
                existing={i['id'] for i in previous['screenshots']}
                if not removed<=existing:raise ValueError('Screenshot does not belong to this entry.')
                if len(existing-removed)+len(images)>MAX_IMAGES:raise ValueError('Use up to four screenshots per entry.')
                self.db.execute('UPDATE entries SET '+','.join(key+'=?' for key in fields)+',updated_at=?,revision=revision+1 WHERE id=?',
                                [*fields.values(),now,entry_id])
            else:
                if removed:raise ValueError('A new entry has no screenshots to remove.')
                entry_id=uuid.uuid4().hex
                self.db.execute('INSERT INTO entries ('+','.join(fields)+',id,created_at,updated_at,revision) VALUES ('+
                                ','.join('?' for _ in range(len(fields)+4))+')', [*fields.values(),entry_id,now,now,1])
            if tagged_characters is not None:
                self.db.execute('DELETE FROM journal_character_tags WHERE entry_id=?',(entry_id,))
                self.db.executemany('INSERT INTO journal_character_tags VALUES (?,?)',[(entry_id,name) for name in tagged_characters])
            if tagged_groups is not None:
                self.db.execute('DELETE FROM journal_group_tags WHERE entry_id=?',(entry_id,))
                for group in tagged_groups:
                    self.db.execute('INSERT INTO journal_group_tags VALUES (?,?,?)',(entry_id,group['id'],group['name']))
                    self.db.executemany('INSERT INTO journal_group_members VALUES (?,?,?)',[(entry_id,group['id'],name) for name in group['members']])
            for image_id in removed:self.db.execute('DELETE FROM screenshots WHERE id=? AND entry_id=?',(image_id,entry_id))
            for image in images:self.db.execute('INSERT INTO screenshots VALUES (?,?,?,?,?)',(image['id'],entry_id,image['name'],image['mime'],image['data']))
            return self._entry(entry_id)

    def delete(self,entry_id,revision):
        identifier(entry_id)
        with self.lock,self.db:
            self.db.execute("BEGIN IMMEDIATE")
            entry=self._entry(entry_id)
            if type(revision)is not int or revision!=entry['revision']:raise JournalConflict('This entry changed. Reopen it before deleting.')
            self.db.execute('DELETE FROM entries WHERE id=?',(entry_id,))
