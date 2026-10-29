"""Explained party priorities and geographic suggestions; no in-game eligibility or navigation claims."""
import json
import math
from pathlib import Path
import time
from armory import read_inventory_sql
from mysql_access import DatabaseError

ROOT=Path(__file__).resolve().parent
MAP_NAMES={0:'Eastern Kingdoms',1:'Kalimdor',530:'Outland',571:'Northrend'}
SEASONAL={-22,-284,-366,-369,-370,-374,-376}


def location_sql(ids):
    if not ids or len(ids)>1000 or any(type(q) is not int or not 1<=q<=2147483647 for q in ids):
        raise ValueError('Choose up to 1000 valid quest IDs.')
    selected=','.join(map(str,sorted(set(ids))))
    queries=[f"""SELECT JSON_OBJECT('kind','location','quest',m.QuestID,'role',IF(m.ObjectiveIndex<0,'handin','objective'),
'source','Quest map area','objective',m.ObjectiveIndex,'map',m.MapID,'world_area',m.WorldMapAreaId,
'zone',0,'x',m.x,'y',m.y,'name','Approximate quest-map area','rank',m.rn)
FROM (SELECT p.QuestID,p.id,p.ObjectiveIndex,p.MapID,p.WorldMapAreaId,AVG(pt.X) x,AVG(pt.Y) y,
ROW_NUMBER() OVER(PARTITION BY p.QuestID ORDER BY p.id) rn FROM acore_world.quest_poi p
JOIN acore_world.quest_poi_points pt ON pt.QuestID=p.QuestID AND pt.Idx1=p.id
WHERE p.QuestID IN ({selected}) GROUP BY p.QuestID,p.id,p.ObjectiveIndex,p.MapID,p.WorldMapAreaId) m WHERE m.rn<=13;"""]
    for table,template,spawn,role,condition in [
        ('creature_questender','creature_template','creature','handin','sp.id=t.entry'),
        ('creature_queststarter','creature_template','creature','start','sp.id=t.entry'),
        ('gameobject_questender','gameobject_template','gameobject','handin','sp.id=t.entry'),
        ('gameobject_queststarter','gameobject_template','gameobject','start','sp.id=t.entry')]:
        queries.append(f"""SELECT JSON_OBJECT('kind','location','quest',m.quest,'role','{role}',
'source','Possible saved spawn','objective',NULL,'map',m.map,'world_area',0,'zone',m.zoneId,
'x',m.position_x,'y',m.position_y,'name',m.name,'entity_type','{'npc' if template=='creature_template' else 'object'}','entity_id',m.entry,'rank',m.rn)
FROM (SELECT r.quest,sp.map,sp.zoneId,sp.position_x,sp.position_y,t.name,t.entry,
ROW_NUMBER() OVER(PARTITION BY r.quest ORDER BY sp.guid) rn
FROM acore_world.{table} r JOIN acore_world.{template} t ON t.entry=r.id
JOIN acore_world.{spawn} sp ON {condition} WHERE r.quest IN ({selected})) m WHERE m.rn<=7;""")
    return '''SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
'''+'\n'.join(queries)+'\nCOMMIT;'


class LocationProvider:
    def __init__(self, reader=None):
        self.reader=reader or (lambda sql:read_inventory_sql(sql,timeout=5));self.cached={}
    def get(self,ids):
        if not ids:return {'locations':{},'warning':None}
        key=tuple(sorted(set(ids)));cached=self.cached.get(key)
        if cached and time.monotonic()-cached[0]<(15 if cached[1]['warning'] else 300):return cached[1]
        try:
            rows=self.reader(location_sql(key));locations={}
            for row in rows:
                if row['kind']=='location':locations.setdefault(row['quest'],[]).append(row)
            result={'locations':locations,'warning':None}
        except (DatabaseError,ValueError):
            result={'locations':{},'warning':'Location lookup unavailable; priorities still use saved quest status.'}
        if len(self.cached)>=32:self.cached.pop(next(iter(self.cached)))
        self.cached[key]=(time.monotonic(),result)
        return result


def load_metadata():
    try:return json.loads((ROOT/'assets'/'quest-metadata.json').read_text())
    except (OSError,ValueError):return {}


def missing_reason(c,q,rows):
    if not c.get('found'):return {'label':'Character not found','confidence':'unknown','reasons':['No saved character record is available.']}
    if not c.get('quest_state_available',True):return {'label':'Live state unavailable','confidence':'unknown','reasons':['Offline live state cannot establish quest availability.']}
    original=next((r for r in rows if r['kind']=='character' and r['guid']==c['guid']),{})
    rewards={r['quest']:bool(r.get('active',1)) for r in rows if r['kind']=='rewarded' and r['guid']==c['guid']}
    repeat=bool((q.get('special_flags') or 0)&17 or (q.get('flags') or 0)&(4096|32768)) if q else False
    if q and rewards.get(q['id']):
        return {'label':'Hand-in recorded','confidence':'recorded','reasons':['Already recorded as handed in.'+(' Repeat/reset availability remains unverified.' if repeat or q.get('category_id') in SEASONAL else '')]}
    if not q or not q.get('template_found'):
        return {'label':'Availability unverified','confidence':'unknown','reasons':['Quest definition is unavailable.']}
    if not original.get('eligibility_data_complete'):
        return {'label':'Availability unverified','confidence':'unknown','reasons':['This source does not include complete eligibility inputs.']}
    blockers=[];notes=[]
    if c['level']<(q.get('min_level') or 0):blockers.append(f"Requires level {q['min_level']} (saved level {c['level']}).")
    if q.get('max_level') and c['level']>q['max_level']:blockers.append(f"Maximum level {q['max_level']} (saved level {c['level']}).")
    for field,char_id,label in [('race_mask',original.get('race'),'race'),('class_mask',original.get('class'),'class')]:
        mask=q.get(field) or 0
        if mask and char_id and not mask&(1<<(char_id-1)):blockers.append(f"Saved {label} does not match this quest's allowed {label} mask.")
    skill=q.get('required_skill')
    if skill:
        value=next((r['value'] for r in rows if r['kind']=='skill' and r['guid']==c['guid'] and r['id']==skill),0)
        if value<(q.get('required_skill_points') or 0):blockers.append(f"Requires skill #{skill} at {q['required_skill_points']} (saved {value}).")
    deps={r['id']:r for r in rows if r['kind']=='dependency' and r['quest']==q['id']}
    if deps:
        simple=all((d.get('group') or 0)>=0 and not (d.get('flags') or 0)&(4096|32768) and not (d.get('special_flags') or 0)&17 and d.get('category_id') not in SEASONAL for d in deps.values())
        active={r['id'] for r in rows if r['kind']=='quest' and r['guid']==c['guid']}
        satisfied=any(rewards.get(d['id']) if d['signed_id']>0 else (d['id'] in active or rewards.get(d['id'])) for d in deps.values())
        if simple and not satisfied and original.get('reward_history_complete'):
            names=', '.join((d.get('title') or f"Quest #{d['id']}")+(' (must be active)' if d['signed_id']<0 else ' (hand-in required)') for d in deps.values())
            blockers.append('No prerequisite alternative satisfied: '+names+'.')
        elif not simple:notes.append('Grouped or reset-dependent prerequisites require in-game verification.')
    elif q.get('prev_quest'):notes.append('Prerequisite definition could not be verified.')
    if q['id'] in rewards and not rewards[q['id']]:notes.append('A prior hand-in record is inactive/reset; repeat availability is unverified.')
    if q.get('rep_min_faction') or q.get('rep_max_faction') or q.get('faction'):notes.append('Reputation requirements have not been evaluated.')
    if q.get('exclusive_group'):notes.append('Exclusive quest-chain rules require in-game verification.')
    if repeat:notes.append('Daily, weekly or repeat/reset availability requires in-game verification.')
    notes.append('Scripts, conditions, quest-log capacity and current quest-giver availability are not evaluated.')
    return {'label':'Known requirement not met' if blockers else 'Not in log · availability unverified',
            'confidence':'blocked' if blockers else 'unknown','reasons':blockers+notes}


def location_label(row,metadata):
    zone=metadata.get('world_areas',{}).get(str(row.get('world_area')),{}).get('area',0) or row.get('zone')
    return metadata.get('areas',{}).get(str(zone)) or f"Map {row['map']} · area unspecified"


def nearest(points,start):
    """Order points within each map by straight-line distance; never bridge map coordinates."""
    remaining=list(points);ordered=[]
    maps=sorted({p['map'] for p in remaining},key=lambda m:(m!=start.get('map'),m))
    for map_id in maps:
        local=[p for p in remaining if p['map']==map_id]
        cursor=(start.get('x'),start.get('y')) if map_id==start.get('map') else (None,None)
        while local:
            if cursor[0] is None:choice=min(local,key=lambda p:(p['zone'],p['priority'],p['x'],p['y']))
            else:choice=min(local,key=lambda p:(math.hypot(p['x']-cursor[0],p['y']-cursor[1]),p['priority'],p['zone']))
            local.remove(choice);ordered.append(choice);cursor=(choice['x'],choice['y'])
    return ordered


def enrich_view(view,rows,geo,metadata):
    definitions={r['id']:r for r in rows if r['kind']=='quest'}
    for q in view['quests']:
        definition=definitions[q['id']]
        category=definition.get('category_id') or 0
        q['zone']=metadata.get('areas' if category>0 else 'sorts',{}).get(str(abs(category))) or ('Uncategorized' if not category else f'Category #{category}')
        q['locations']=[]
        for raw in geo.get('locations',{}).get(q['id'],[]):
            row=dict(raw)
            if not row.get('world_area'):
                markers=[p for p in geo.get('locations',{}).get(q['id'],[]) if p.get('world_area') and p['role']==row['role'] and p['map']==row['map']]
                if markers:
                    marker=min(markers,key=lambda p:math.hypot(row['x']-p['x'],row['y']-p['y']))
                    if math.hypot(row['x']-marker['x'],row['y']-marker['y'])<=2000:row['world_area']=marker['world_area']
            row['zone']=location_label(row,metadata);row['map_name']=MAP_NAMES.get(row['map'],f"Map #{row['map']}")
            row['approximate']=row['source']=='Quest map area';q['locations'].append(row)
        for c,p in zip(view['characters'],q['progress']):
            if p['status'] in ('missing','rewarded','unavailable'):p['explanation']=missing_reason(c,definition,rows)
    actions=[];unknown=[];stops=[]
    for q in view['quests']:
        members=list(zip(view['characters'],q['progress']))
        ready=[c['name'] for c,p in members if p['status']=='ready']
        active=[c['name'] for c,p in members if p['status']=='active']
        behind=[c['name'] for c,p in members if p['status']=='active' and p['behind']]
        def action(kind,names,text,reason,priority):
            value={'kind':kind,'quest':q['id'],'title':q['title'],'characters':names,'text':text,'reason':reason,'priority':priority,'zone':q['zone']}
            actions.append(value);return value
        tasks=[]
        if ready:tasks.append(action('handin',ready,f"Turn in {q['title']}", 'Saved quest status is ready for these characters; counters alone were not used.',0))
        if len(active)>=2:tasks.append(action('shared',active,f"Work on {q['title']} together",'These characters have the same unfinished quest.',1))
        elif len(active)==1:tasks.append(action('side',active,f"Individual work: {q['title']}",'Only this character currently needs progress on this quest; race alone does not determine side work.',3))
        if behind:action('catchup',behind,f"Catch up on {q['title']}",'These characters are behind a participant on a saved objective or completion status.',2)
        failed=[c['name'] for c,p in members if p['status']=='failed']
        if failed:action('failed',failed,f"Review failed quest: {q['title']}",'Saved status is failed; check recovery options in game.',4)
        uncertain=[c['name'] for c,p in members if p['status']=='missing' and c.get('found') and p.get('explanation',{}).get('confidence')=='unknown']
        if uncertain:action('check',uncertain,f"Check availability of {q['title']}",'Not in the saved log. Check the listed requirements before travelling or trying to accept it.',5)
        for task in tasks:
            role='handin' if task['kind']=='handin' else 'objective'
            choices=[loc for loc in q['locations'] if loc['role']==role]
            if role=='objective':
                pending=set();other=False
                for obj in q['objectives']:
                    incomplete=any(p['status']=='active' and (p['counts'].get(obj['key']) is None or p['counts'][obj['key']]<obj['required']) for _,p in members)
                    if not incomplete:continue
                    key=obj['key']
                    if key.startswith('target'):pending.add(int(key[6:])-1)
                    elif key.startswith('item'):pending.add(int(key[4:])+3)
                    else:other=True
                choices=[loc for loc in choices if other or loc.get('objective') in pending]
            else:
                # Prefer explicit contact locations; POI hand-in markers are a fallback.
                contacts=[loc for loc in choices if not loc['approximate']]
                if contacts:choices=contacts
            if not choices:
                unknown.append({'quest':q['id'],'title':q['title'],'characters':task['characters'],'role':role,'category':q['zone']});continue
            # Choose among all candidates separately for each saved starting position.
            for loc in choices:
                objective_label=next((o['label'] for o in q['objectives'] if (int(o['key'][6:])-1 if o['key'].startswith('target') else int(o['key'][4:])+3 if o['key'].startswith('item') else None)==loc.get('objective')),None) if role=='objective' else None
                stops.append({**loc,'objective_label':objective_label,'quest':q['id'],'title':q['title'],'characters':task['characters'],
                              'task':task['text'],'priority':task['priority'],'alternative':len(choices)>1})
    actions.sort(key=lambda a:(a['priority'],-len(a['characters']),a['title'].casefold()))
    def route_for(start):
        alternatives={}
        for stop in stops:
            key=(stop['quest'],stop['role'],stop.get('objective') if stop['role']=='objective' else None)
            alternatives.setdefault(key,[]).append(stop)
        chosen=[]
        for candidates in alternatives.values():
            def cost(loc):
                same=loc['map']==start.get('map')
                distance=math.hypot(loc['x']-start['x'],loc['y']-start['y']) if same else 0
                return (not same,distance,loc['map'],loc['zone'],loc['x'],loc['y'])
            chosen.append(min(candidates,key=cost))
        grouped=[]
        for stop in sorted(chosen,key=lambda s:(s['map'],s['zone'],s['priority'],s['quest'])):
            same=next((g for g in grouped if g['map']==stop['map'] and g['zone']==stop['zone'] and math.hypot(g['x']-stop['x'],g['y']-stop['y'])<=1000),None)
            item={k:stop[k] for k in ('quest','title','characters','task','source','name','alternative','approximate','objective_label')}
            if same:same['activities'].append(item);same['priority']=min(same['priority'],stop['priority'])
            else:grouped.append({'map':stop['map'],'map_name':stop['map_name'],'zone':stop['zone'],'x':stop['x'],'y':stop['y'],'priority':stop['priority'],'activities':[item]})
        return nearest(grouped,start)
    starts=[];routes={}
    for c in view['characters']:
        raw=next((r for r in rows if r['kind']=='character' and r.get('guid')==c.get('guid')),None)
        if raw and all(raw.get(k) is not None for k in ('map','x','y')):
            starts.append({'guid':c['guid'],'name':c['name'],'map':raw['map'],'x':raw['x'],'y':raw['y']})
    if not starts:routes['unknown']=route_for({})
    for start in starts:routes[str(start['guid'])]=route_for(start)
    view['planning']={'actions':actions,'routes':routes,'starts':starts,'unknown_locations':unknown,'warning':geo.get('warning'),
                      'location_note':'Possible saved spawns and approximate quest-map areas; phases, terrain, travel links and current NPC availability are not verified. One candidate per activity is suggested; inspect alternatives before travelling. Different maps are separate legs.'}
    return view
