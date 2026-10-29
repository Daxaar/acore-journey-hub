"""Saved character skills and a server-derived profession recipe catalogue; read only."""
from datetime import datetime,timezone
import json
from pathlib import Path
import threading
import time
from armory import read_inventory_sql
from mysql_access import name_filter,DatabaseError

ROOT=Path(__file__).resolve().parent
CATEGORIES={7:'Class Skills',11:'Professions',9:'Secondary Skills',6:'Weapon Skills',8:'Armor Proficiencies',10:'Languages',5:'Attributes',12:'Other Skills'}
GATHERING={182,186,393,356}
SECONDARY={129,185,356}
WEAPONS={0:'One-Handed Axes',1:'Two-Handed Axes',2:'Bows',3:'Guns',4:'One-Handed Maces',5:'Two-Handed Maces',6:'Polearms',7:'One-Handed Swords',8:'Two-Handed Swords',10:'Staves',13:'Fist Weapons',15:'Daggers',16:'Thrown',18:'Crossbows',19:'Wands',20:'Fishing Poles'}
ARMOR={1:'Cloth',2:'Leather',3:'Mail',4:'Plate',6:'Shields'}


def skills_sql(names,recipes=False):
    if not isinstance(names,(list,tuple)) or not 1<=len(names)<=6:raise ValueError('Choose between 1 and 6 characters.')
    if any(not isinstance(n,str) for n in names):raise ValueError('Choose valid character names.')
    selected=name_filter('c',names)
    extra=''
    if recipes:
        if len(names)!=1:raise ValueError('Choose one character for recipes.')
        extra=f"""SELECT JSON_OBJECT('kind','spell','guid',c.guid,'id',sp.spell)
FROM acore_characters.characters c JOIN acore_characters.character_spell sp ON sp.guid=c.guid
WHERE {selected} ORDER BY sp.spell LIMIT 20001;
SELECT JSON_OBJECT('kind','material','id',i.itemEntry,'count',SUM(i.count))
FROM acore_characters.characters c JOIN acore_characters.character_inventory v ON v.guid=c.guid
JOIN acore_characters.item_instance i ON i.guid=v.item
LEFT JOIN acore_characters.character_inventory b ON b.guid=c.guid AND b.item=v.bag AND b.bag=0 AND b.slot BETWEEN 19 AND 22
LEFT JOIN acore_characters.item_instance bi ON bi.guid=b.item
LEFT JOIN acore_world.item_template bt ON bt.entry=bi.itemEntry
WHERE {selected} AND ((v.bag=0 AND v.slot BETWEEN 23 AND 38) OR
(b.item IS NOT NULL AND v.slot<bt.ContainerSlots AND bt.ContainerSlots BETWEEN 0 AND 64))
GROUP BY i.itemEntry LIMIT 2001;"""
    return f"""SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
SELECT JSON_OBJECT('kind','character','guid',c.guid,'name',c.name,'race',c.race,'class',c.class,'level',c.level)
FROM acore_characters.characters c WHERE {selected};
SELECT JSON_OBJECT('kind','skill','guid',c.guid,'id',s.skill,'value',s.value,'max',s.max)
FROM acore_characters.characters c JOIN acore_characters.character_skills s ON s.guid=c.guid
WHERE {selected} ORDER BY c.guid,s.skill LIMIT 2001;
{extra}
COMMIT;
"""


def skill_records(rows,metadata,names):
    if sum(r['kind']=='skill' for r in rows)>=2001 or sum(r['kind']=='spell' for r in rows)>=20001 or sum(r['kind']=='material' for r in rows)>=2001:
        raise DatabaseError('Skill data exceeds the dashboard limit; no partial result was displayed.')
    found={r['name'].lower():r for r in rows if r['kind']=='character'};characters=[]
    for name in names:
        c=found.get(name.lower())
        if not c:characters.append({'name':name,'found':False,'skills':[]});continue
        skills=[]
        for row in rows:
            if row['kind']!='skill' or row['guid']!=c['guid']:continue
            definition=metadata.get('skills',{}).get(str(row['id']),{})
            category=definition.get('category',0)
            skills.append({**row,'name':definition.get('name') or f"Skill #{row['id']}",
                           'description':definition.get('description',''),'category':category,'group':('Racial Skills' if 'racial' in definition.get('name','').lower() else CATEGORIES.get(category,'Other Skills')),
                           'profession':category==11 or row['id'] in SECONDARY,'gathering':row['id'] in GATHERING,'icon':definition.get('icon')})
        skills.sort(key=lambda s:(list(CATEGORIES).index(s['category']) if s['category'] in CATEGORIES else 99,s['name'].casefold()))
        characters.append({**c,'found':True,'skills':skills})
    return characters


def applicable(ability,c):
    race=1<<(c['race']-1);cls=1<<(c['class']-1)
    return (not ability['race'] or ability['race']&race) and (not ability['class'] or ability['class']&cls) and not ability['exclude_race']&race and not ability['exclude_class']&cls


def difficulty(value,ability,learned):
    if not learned:return 'unlearned'
    if value<ability['required']:return 'unavailable'
    gray,yellow=ability['gray'],ability['yellow']
    if gray and value>=gray:return 'gray'
    if gray and value>=(yellow+gray)//2:return 'green'
    if yellow and value>=yellow:return 'yellow'
    return 'orange'


def recipe_records(rows,metadata,character,skill_id):
    skill=next((s for s in character['skills'] if s['id']==skill_id),None);value=skill['value'] if skill else 0
    known={r['id'] for r in rows if r['kind']=='spell'};counts={r['id']:r['count'] for r in rows if r['kind']=='material'}
    items=metadata.get('items',{});recipes=[]
    def item(entry):return items.get(str(entry),{'id':entry,'name':f'Item #{entry}','icon':None})
    for record in metadata.get('recipes',{}).get(str(skill_id),{}).values():
        matches=[a for a in record['abilities'] if applicable(a,character)]
        ability=min(matches or record['abilities'],key=lambda a:a['required'])
        explicit=record['id'] in known
        automatic=bool(skill and any(a.get('acquire')==2 or (a.get('acquire')==1 and value>=a['required']) for a in matches))
        learned=explicit or automatic
        superseded=not learned and any(a['superseded'] in known for a in record['abilities'] if a['superseded'])
        status='learned' if learned else 'superseded' if superseded else 'unlearned'
        requirements={}
        for entry,n in record['reagents']:requirements[entry]=requirements.get(entry,0)+n
        reagents=[{**item(entry),'required':n,'owned':counts.get(entry,0)} for entry,n in requirements.items()]
        outputs=[{**item(o['id']),'minimum':o['minimum'],'maximum':o['maximum']} for o in record.get('outputs',[])]
        group='Other'
        if outputs:
            out=outputs[0]
            if out.get('class')==2:group=WEAPONS.get(out.get('subclass'),'Weapons')
            elif out.get('class')==4:group=ARMOR.get(out.get('subclass'),'Armor')
            elif out.get('class')==0:group='Other' if out.get('subclass')==8 else 'Consumables'
            elif out.get('class')==7:group='Materials & parts'
        material_count=min((r['owned']//r['required'] for r in reagents),default=None)
        recipes.append({'id':record['id'],'name':record['name'],'rank':record.get('rank',''),'description':record.get('description') or '',
                        'status':status,'learning_source':'Saved spellbook' if explicit else 'Granted by saved skill' if automatic else '', 'required_skill':ability['required'],'restricted':not bool(matches),'difficulty':difficulty(value,ability,learned),
                        'group':group,'outputs':outputs,'reagents':reagents,'icon':outputs[0].get('icon') if outputs else record.get('icon'),
                        'material_count':material_count,'has_materials':all(r['owned']>=r['required'] for r in reagents),
                        'tools':[item(i) for i in record['tools']],
                        'tool_categories':[metadata.get('tool_categories',{}).get(str(i),f'Tool category #{i}') for i in record['tool_categories']],
                        'focus':metadata.get('focuses',{}).get(str(record.get('focus')),f"Workstation #{record['focus']}" if record.get('focus') else ''),
                        'base':record.get('base',[])})
    recipes.sort(key=lambda r:(r['group']!='Other',r['group'],r['required_skill'],r['name'].casefold(),r['id']))
    return recipes


class SkillsProvider:
    def __init__(self,root=ROOT,reader=read_inventory_sql):
        self.reader=reader;self.lock=threading.Lock();self.cached={}
        try:self.metadata=json.loads((root/'assets'/'profession-metadata.json').read_text())
        except (OSError,ValueError):self.metadata={}
        if not isinstance(self.metadata,dict) or not all(isinstance(self.metadata.get(k),dict) for k in ('skills','recipes','items')):self.metadata={}

    def get(self,names,skill_id=None):
        sql=skills_sql(names,skill_id is not None)
        if not self.metadata:raise DatabaseError('Skill catalogue is unavailable. Prepare the local profession assets first.')
        if skill_id is not None:
            if type(skill_id) is not int or str(skill_id) not in self.metadata.get('skills',{}) or not (self.metadata['skills'][str(skill_id)]['category']==11 or skill_id in SECONDARY):
                raise ValueError('Choose a supported profession.')
        key=(tuple(n.lower() for n in names),skill_id)
        with self.lock:
            cached=self.cached.get(key)
            if cached and time.monotonic()-cached[0]<2:return cached[1]
            if not self.metadata:raise DatabaseError('Skill catalogue is unavailable. Prepare the local profession assets first.')
            rows=self.reader(sql);characters=skill_records(rows,self.metadata,names)
            data={'characters':characters,'refreshed_at':datetime.now(timezone.utc).isoformat(),
                  'professions':[dict(s,gathering=s['id'] in GATHERING,has_recipes=bool(self.metadata.get('recipes',{}).get(str(s['id'])))) for s in self.metadata['skills'].values() if s['category']==11 or s['id'] in SECONDARY]}
            data['professions'].sort(key=lambda s:(s['category']!=11,s['name']))
            if skill_id is not None:
                if not characters[0]['found']:raise LookupError('No saved character found with that name.')
                data['recipes']=recipe_records(rows,self.metadata,characters[0],skill_id);data['skill_id']=skill_id
            if len(self.cached)>=64:self.cached.pop(next(iter(self.cached)))
            self.cached[key]=(time.monotonic(),data);return data
