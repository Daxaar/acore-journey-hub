"""Read-only class-trainer progression based on saved character state and server data."""
from datetime import datetime,timezone
from pathlib import Path
import re
import threading
import time
from armory import read_inventory_sql
from item_tooltips import load_metadata
from mysql_access import DatabaseError,name_filter
from spell_tooltips import CLASSES,spell_text

ROOT=Path(__file__).resolve().parent
MODES={'upcoming','unlearned','available','all'}


def training_sql(name):
    if not isinstance(name,str):raise ValueError('Choose a valid character name.')
    selected=name_filter('c',[name])
    return f'''SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
SELECT JSON_OBJECT('kind','character','guid',c.guid,'name',c.name,'class',c.class,'race',c.race,'level',c.level)
FROM acore_characters.characters c WHERE {selected} LIMIT 2;
SELECT JSON_OBJECT('kind','known','id',s.spell) FROM acore_characters.character_spell s
JOIN acore_characters.characters c ON c.guid=s.guid WHERE {selected} LIMIT 20001;
SELECT JSON_OBJECT('kind','skill','id',s.skill,'value',s.value) FROM acore_characters.character_skills s
JOIN acore_characters.characters c ON c.guid=s.guid WHERE {selected} LIMIT 2001;
COMMIT;
'''


def level_bounds(value):
    if not isinstance(value,str) or len(value)>12:raise ValueError('Enter a level or range, such as 14 or 14–20.')
    if not value.strip():return 1,255
    match=re.fullmatch(r'\s*([0-9]{1,3})(?:\s*[-–]\s*([0-9]{1,3}))?\s*',value)
    if not match:raise ValueError('Enter a level or range, such as 14 or 14–20.')
    low=int(match[1]);high=int(match[2] or match[1])
    if not 1<=low<=high<=255:raise ValueError('Required levels must be between 1 and 255, in ascending order.')
    return low,high


def ability_details(sid,metadata):
    spell=metadata['spells'][str(sid)];text,complete=spell_text(sid,metadata,allow_partial=True)
    power_type=spell.get('power_type',0);cost=spell.get('cost',0)
    power={-2:'Health',0:'Mana',1:'Rage',2:'Focus',3:'Energy',6:'Runic Power'}.get(power_type,'Power')
    if power_type in (1,6):cost/=10
    cost_text=(f"{spell['cost_percent']}% of base {power.lower()}" if spell.get('cost_percent') else f'{cost:g} {power}' if cost else '')
    ranges=metadata.get('ranges',{}).get(str(spell.get('range')),[])
    return {'id':sid,'name':spell.get('name') or f'Spell #{sid}','rank':spell.get('rank') or '','icon':spell.get('icon'),
            'passive':bool(spell.get('attributes',0)&64),'description':text,'description_complete':complete,
            'cast_time_ms':metadata.get('casts',{}).get(str(spell.get('cast'))),
            'cooldown_ms':max(spell.get('recovery',0),spell.get('category_recovery',0)),
            'range_yards':max(ranges) if ranges else None,'power_cost':cost_text,
            'cost_scales':bool(spell.get('cost_per_level'))}


def training_records(rows,metadata):
    characters=[r for r in rows if r['kind']=='character']
    if not characters:raise LookupError('No saved character found with that name.')
    if len(characters)!=1:raise DatabaseError('Character identity is ambiguous; no training list was shown.')
    if sum(r['kind']=='known' for r in rows)>=20001 or sum(r['kind']=='skill' for r in rows)>=2001:
        raise DatabaseError('Saved spell/skill data exceeds the supported limit; no partial list was shown.')
    character={k:v for k,v in characters[0].items() if k!='kind'};character['class_name']=CLASSES.get(character['class'],'Unknown class')
    if any(type(character[k]) is not int or not 1<=character[k]<=32 for k in ('class','race')):raise DatabaseError('Saved race or class is unsupported.')
    training=metadata['training'];spells=metadata['spells'];known={r['id'] for r in rows if r['kind']=='known'}
    skills={r['id']:r['value'] for r in rows if r['kind']=='skill'};talents=set(training['talents'])
    ranks={r['id']:r for r in training['ranks']};chains={}
    for r in training['ranks']:chains.setdefault(r['first'],{})[r['rank']]=r['id']
    known_ranks={}
    for sid in known:
        rank=ranks.get(sid)
        if rank:known_ranks[rank['first']]=max(rank['rank'],known_ranks.get(rank['first'],0))
    abilities={};rules={};extra={}
    for r in training['abilities']:abilities.setdefault(r['spell'],[]).append(r)
    for r in training['skill_rules']:rules.setdefault(r['skill'],[]).append(r)
    for r in training['requirements']:extra.setdefault(r['id'],set()).add(r['required'])
    race=1<<(character['race']-1);cls=1<<(character['class']-1)
    def mask_fit(rule):return (not rule['race'] or rule['race']&race) and (not rule['class'] or rule['class']&cls)
    def fits(sid):
        entries=abilities.get(sid,[])
        return not entries or any(mask_fit(entry) and any(mask_fit(rule) for rule in rules.get(entry['skill'],[])) for entry in entries)
    candidates={};skipped=0
    for offer in training['offers']:
        wrapper=offer['spell']
        if offer['class']!=character['class'] or wrapper in talents or not fits(wrapper):continue
        definition=spells.get(str(wrapper))
        if not definition:skipped+=1;continue
        targets=[sid for effect,sid in zip(definition.get('effects',[]),definition.get('triggers',[])) if effect==36 and sid>0] or [wrapper]
        for sid in dict.fromkeys(targets):
            if sid in talents or not fits(sid):continue
            if str(sid) not in spells:skipped+=1;continue
            rank=ranks.get(sid)
            learned=sid in known or wrapper in known or bool(rank and known_ranks.get(rank['first'],0)>=rank['rank'])
            required=set(a for a in offer['abilities'] if a>0)|extra.get(wrapper,set())|extra.get(sid,set())
            if rank and rank['rank']>1:
                previous=chains[rank['first']].get(rank['rank']-1)
                if previous:required.add(previous)
            missing=sorted(required-known);notes=[]
            if offer['skill'] and skills.get(offer['skill'],0)<offer['skill_rank']:
                notes.append(f"Requires skill #{offer['skill']} at {offer['skill_rank']} (saved {skills.get(offer['skill'],0)}).")
            for required_id in missing:
                spell=spells.get(str(required_id),{})
                notes.append('Requires '+spell.get('name',f'Spell #{required_id}')+(' ('+spell['rank']+')' if spell.get('rank') else '')+'.')
            level=max(1,offer['level']);difference=level-character['level']
            state='known' if learned else 'available' if difference<=0 and not notes else 'blocked' if difference<=0 else 'soon' if difference<=2 else 'later'
            row={**ability_details(sid,metadata),'required_level':level,'state':state,'base_cost':offer['cost'],'requirements':notes}
            # Prefer a currently valid offer; otherwise report the earliest trainer level.
            key=(0 if state=='available' else 1,level,len(notes),offer['cost'])
            if sid not in candidates or key<candidates[sid][0]:candidates[sid]=(key,row)
    records=sorted((row for key,row in candidates.values()),key=lambda r:(r['required_level'],r['name'].casefold(),r['id']))
    return {'character':character,'abilities':records,'skipped':skipped,'refreshed_at':datetime.now(timezone.utc).isoformat()}


class TrainingProvider:
    def __init__(self,root=ROOT,reader=read_inventory_sql):
        self.metadata=load_metadata(root);self.reader=reader;self.lock=threading.Lock();self.cached={}
        t=self.metadata.get('training')
        if not isinstance(t,dict) or not all(isinstance(t.get(key),list) for key in ['offers','ranks','requirements','talents','abilities','skill_rules']):self.metadata={}

    def get(self,name,search='',level='',mode='upcoming'):
        sql=training_sql(name);low,high=level_bounds(level)
        if not isinstance(mode,str) or mode not in MODES:raise ValueError('Choose a supported training view.')
        if not isinstance(search,str) or len(search)>100:raise ValueError('Search names with up to 100 characters.')
        if not self.metadata:raise DatabaseError('Training catalogue unavailable. Run prepare_tooltip_assets.py and restart Character Hub.')
        key=name.lower()
        with self.lock:
            cached=self.cached.get(key)
            if cached and time.monotonic()-cached[0]<2:data=cached[1]
            else:
                data=training_records(self.reader(sql),self.metadata)
                if len(self.cached)>=64:self.cached.pop(next(iter(self.cached)))
                self.cached[key]=(time.monotonic(),data)
        terms=search.casefold().split();visible=[]
        counts={state:sum(r['state']==state for r in data['abilities']) for state in ('available','soon','later','blocked','known')}
        for row in data['abilities']:
            if not low<=row['required_level']<=high:continue
            if mode=='upcoming' and row['state'] not in ('soon','later'):continue
            if mode=='unlearned' and row['state']=='known':continue
            if mode=='available' and row['state']!='available':continue
            text=(row['name']+' '+row['rank']+' '+str(row['id'])).casefold()
            if all(term in text for term in terms):visible.append(row)
        return {**data,'abilities':visible,'counts':counts,'total':len(data['abilities']),
                'warning':f"{data['skipped']} trainer offer(s) had missing spell metadata and were omitted." if data['skipped'] else None}
