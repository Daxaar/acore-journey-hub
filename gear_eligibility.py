"""Planner-only class/race/faction checks, mirroring mandatory quest paths and giver reactions."""
from collections import defaultdict
from gear_sources import query
from mysql_access import DatabaseError


def read_eligibility(reader):
    records={};last=0
    for _ in range(30):
        sql=f'''SELECT JSON_OBJECT('kind','eligibility','id',q.ID,'races',q.AllowableRaces,
'classes',COALESCE(a.AllowableClasses,0),'prev',COALESCE(a.PrevQuestID,0),'next',COALESCE(a.NextQuestID,0),
'group',COALESCE(a.ExclusiveGroup,0),'auto',q.QuestType=0 OR (q.Flags & 524288)<>0 OR (COALESCE(a.SpecialFlags,0) & 4)<>0)
FROM acore_world.quest_template q LEFT JOIN acore_world.quest_template_addon a ON a.ID=q.ID
WHERE q.ID>{last} ORDER BY q.ID LIMIT 1000;'''
        rows=query(sql,reader)
        for row in rows:records[row['id']]=row
        if len(rows)<1000:break
        last=max(records)
    else:raise DatabaseError('Quest eligibility catalogue exceeds the planner limit.')
    for table,template,key,is_object in [
        ('creature_queststarter','creature_template','starters',False),('creature_questender','creature_template','enders',False),
        ('gameobject_queststarter','gameobject_template_addon','objects',True),('gameobject_questender','gameobject_template_addon','end_objects',True)]:
        join='LEFT JOIN' if is_object else 'JOIN'
        contacts=query("SELECT JSON_OBJECT('kind','eligibility_contact','id',r.quest,'faction',COALESCE(c.faction,0)) FROM acore_world."+table+
                       ' r '+join+' acore_world.'+template+' c ON c.entry=r.id LIMIT 30001;',reader)
        if len(contacts)>=30001:raise DatabaseError('Quest contact catalogue exceeds the planner limit.')
        for row in contacts:
            if row['id'] in records:records[row['id']].setdefault(key,[]).append(row['faction'])
    starts=query("SELECT JSON_OBJECT('kind','eligibility_item','id',startquest,'classes',AllowableClass,'races',AllowableRace,'flags',FlagsExtra) FROM acore_world.item_template WHERE startquest>0 LIMIT 30001;",reader)
    if len(starts)>=30001:raise DatabaseError('Quest starting-item catalogue exceeds the planner limit.')
    for row in starts:
        if row['id'] in records:records[row['id']].setdefault('items',[]).append([row['classes'],row['races'],row['flags']])
    conditions=query('''SELECT JSON_OBJECT('kind','eligibility_condition','source',SourceTypeOrReferenceId,
'quest',SourceEntry,'else_group',ElseGroup,'type',ConditionTypeOrReference,'target',ConditionTarget,
'value',ConditionValue1,'negative',NegativeCondition,'script',ScriptName)
FROM acore_world.conditions WHERE SourceTypeOrReferenceId=19 OR SourceTypeOrReferenceId<0 LIMIT 20001;''',reader)
    if len(conditions)>=20001:raise DatabaseError('Quest condition catalogue exceeds the planner limit.')
    return records,conditions


def mask_allows(mask,value):return not mask or mask<0 or bool(mask&(1<<(value-1)))


def any_path(values):
    values=list(values)
    return True if True in values else None if None in values else False


def all_paths(values):
    values=list(values)
    return False if False in values else None if None in values else True


def npc_faction_access(metadata,race,faction):
    """Static faction access; neutral merchants are usable, unknown templates are unverified."""
    templates=metadata.get('faction_templates',{})
    player=templates.get(str(metadata.get('player_factions',{}).get(str(race))))
    template=templates.get(str(faction))
    if not template or not player:return None
    player_faction=player['faction']
    if player_faction and player_faction in template.get('enemies',[]):return False
    if player_faction and player_faction in template.get('friends',[]):return True
    return not bool(template['hostile']&player['group'])


class QuestEligibility:
    def __init__(self,records,metadata,conditions=()):
        self.records=records;self.templates=metadata.get('faction_templates',{});self.races=metadata.get('player_factions',{})
        self.previous=defaultdict(set);self.groups=defaultdict(list);self.conditions=defaultdict(list);self.references=defaultdict(list)
        for qid,q in records.items():
            if q.get('prev'):self.previous[qid].add(q['prev'])
            if q.get('next') in records:self.previous[q['next']].add(qid)
            if q.get('group',0)<0:self.groups[q['group']].append(qid)
        for condition in conditions:
            if condition['source']<0:self.references[-condition['source']].append(condition)
            elif condition['source']==19:self.conditions[condition['quest']].append(condition)

    def for_character(self,char):
        cache={};visiting=set();race=char['race'];cls=char['class']
        active=lambda qid:char.get('quests',{}).get(qid) in (1,3,5)
        def giver(faction,is_object=False):
            if faction==0 and is_object:return True
            return npc_faction_access({'faction_templates':self.templates,'player_factions':self.races},race,faction)
        def contact(q,end=False):
            creatures=q.get('enders' if end else 'starters') or []
            objects=q.get('end_objects' if end else 'objects') or []
            paths=[giver(f) for f in creatures]+[giver(f,True) for f in objects]
            if not end:
                for definition in q.get('items') or []:
                    c,r=definition[:2];extra=definition[2] if len(definition)>2 else 0
                    alliance=race in (1,3,4,7,11)
                    paths.append(bool(c&(1<<(cls-1))) and bool(r&(1<<(race-1))) and not (extra&1 and alliance or extra&2 and not alliance))
            if not paths:return True if end or q.get('auto') else None
            return any_path(paths)
        def conditions_pass(rows,refs=frozenset(),in_reference=False):
            branches=defaultdict(list)
            for condition in rows:
                kind=condition['type'];value=condition['value'];result=None
                if kind<0:
                    ref=-kind
                    result=None if ref in refs or ref not in self.references else conditions_pass(self.references[ref],refs|{ref},True)
                elif condition.get('target',0)==0:
                    if kind==6:result=value==(469 if race in (1,3,4,7,11) else 67)
                    elif kind==15:result=bool(value&(1<<(cls-1)))
                    elif kind==16:result=bool(value&(1<<(race-1)))
                relevant=kind<0 or kind in (6,15,16) and condition.get('target',0)==0
                if not relevant and not in_reference:result=True
                elif result is not None and condition.get('negative'):result=not result
                if condition.get('script') and result is not False:result=None
                branches[condition['else_group']].append(result)
            # Other condition types do not establish class/faction exclusion; full availability remains checked separately.
            return any_path(all_paths(values) for values in branches.values()) if branches else True
        def evaluate(qid,depth=0,as_previous=False,needs_reward=True):
            if as_previous and (qid in char.get('rewarded',set()) if needs_reward else active(qid)):return True
            key=(qid,needs_reward)
            if key in cache:return cache[key]
            if qid in visiting or depth>=64:return None
            q=self.records.get(qid)
            if not q:return None
            if not mask_allows(q.get('races',0),race) or not mask_allows(q.get('classes',0),cls):cache[key]=False;return False
            condition_result=conditions_pass(self.conditions.get(qid,[]))
            if condition_result is not True:cache[key]=condition_result;return condition_result
            visiting.add(qid)
            paths=[]
            for signed in self.previous[qid]:
                parent=abs(signed);record=self.records.get(parent)
                if record and record.get('group',0)<0:
                    paths.append(all_paths(evaluate(member,depth+1,True,signed>0) for member in self.groups[record['group']]))
                else:paths.append(evaluate(parent,depth+1,True,signed>0))
            chain=any_path(paths) if paths else True
            # An accepted quest already demonstrates a start path, but not the right to use a hostile turn-in NPC.
            start=True if active(qid) else contact(q)
            result=all_paths([chain,start,contact(q,True) if needs_reward else True])
            visiting.remove(qid);cache[key]=result;return result
        return evaluate
