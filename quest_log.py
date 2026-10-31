"""Bounded saved quest journal and world quest catalogue, independent of the comparison source."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import threading
import time

from mysql_access import CONTAINER, DatabaseError, name_filter
from armory import ITEM_TOOLTIP_FIELDS

ROOT = Path(__file__).resolve().parent
PAGE_SIZE = 50
STATUSES = {1:'ready', 3:'active', 5:'failed'}
CLASSES = {1:'Warrior',2:'Paladin',3:'Hunter',4:'Rogue',5:'Priest',6:'Death Knight',
           7:'Shaman',8:'Mage',9:'Warlock',11:'Druid'}


ALLIANCE_RACES = sum(1 << (race-1) for race in (1,3,4,7,11))
HORDE_RACES = sum(1 << (race-1) for race in (2,5,6,8,10))
PLAYABLE_RACES = ALLIANCE_RACES | HORDE_RACES


def quest_faction(race_mask, prerequisite_masks=()):
    """Only label a faction supported by explicit mandatory race restrictions."""
    possible = PLAYABLE_RACES
    for mask in (race_mask, *(prerequisite_masks or ())):
        if mask is None or mask in (0, -1, 0xffffffff):
            continue
        if type(mask) is not int or mask < 0 or mask & ~PLAYABLE_RACES:
            return None
        possible &= mask
    if possible and possible & ALLIANCE_RACES and not possible & HORDE_RACES:
        return 'alliance'
    if possible and possible & HORDE_RACES and not possible & ALLIANCE_RACES:
        return 'horde'
    return None


def prerequisite_races_sql(depth=6):
    # Follow only positive mandatory prerequisites with no alternative exclusive group.
    joins=[]
    for i in range(1,depth+1):
        joins += [f'LEFT JOIN acore_world.quest_template_addon fr{i} ON fr{i}.ID=fr{i-1}.PrevQuestID '
                  f'AND fr{i-1}.PrevQuestID>0 AND fr{i}.ExclusiveGroup=0',
                  f'LEFT JOIN acore_world.quest_template fq{i} ON fq{i}.ID=fr{i}.ID']
    return '(SELECT JSON_ARRAY('+','.join(f'fq{i}.AllowableRaces' for i in range(1,depth+1))+') '+\
           'FROM acore_world.quest_template_addon fr0 '+ ' '.join(joins)+' WHERE fr0.ID=q.ID)'


def parameters(mode='active', name='', search='', page=0, quest_id=None, class_id=0):
    if type(class_id) is not int or class_id not in (0, *CLASSES):
        raise ValueError('Choose all classes or a valid WotLK class.')
    if mode not in ('active','completed','all'):
        raise ValueError('Choose active, completed or all quests.')
    if mode != 'all': name_filter('c', [name])
    if not isinstance(search,str) or len(search) > 100 or any(ord(c) < 32 for c in search):
        raise ValueError('Search with up to 100 printable characters.')
    if type(page) is not int or not 0 <= page <= 10000:
        raise ValueError('Invalid quest page.')
    if quest_id is not None and (type(quest_id) is not int or not 1 <= quest_id <= 2147483647):
        raise ValueError('Invalid quest ID.')


def source(mode, name):
    if mode == 'all': return 'FROM acore_world.quest_template q', '1=1'
    if mode == 'active':
        return ('''FROM acore_characters.characters c
JOIN acore_characters.character_queststatus s ON s.guid=c.guid AND s.status IN (1,3,5)
LEFT JOIN acore_world.quest_template q ON q.ID=s.quest''', name_filter('c',[name]))
    return ('''FROM acore_characters.characters c
JOIN acore_characters.character_queststatus_rewarded s ON s.guid=c.guid
LEFT JOIN acore_world.quest_template q ON q.ID=s.quest''', name_filter('c',[name]))


def query_sql(mode='active', name='', search='', page=0, quest_id=None, class_id=0):
    parameters(mode,name,search,page,quest_id,class_id)
    origin, where = source(mode,name)
    where += " AND UPPER(COALESCE(q.LogTitle,'')) NOT REGEXP '<[[:space:]]*(UNUSED|DEPRECATED)[[:space:]]*>'"
    if class_id:
        origin += '\nLEFT JOIN acore_world.quest_template_addon class_filter ON class_filter.ID=q.ID'
        # A selected class means quests restricted to that class, not the general catalogue.
        where += f' AND class_filter.AllowableClasses={1 << (class_id-1)}'
    qid = 'q.ID' if mode == 'all' else 's.quest'
    if quest_id is not None: where += f' AND {qid}={quest_id}'
    elif search:
        literal = '0x'+search.encode('utf-8').hex()
        where += f" AND (LOCATE(LOWER(CONVERT({literal} USING utf8mb4)),LOWER(CONCAT_WS(' ',q.LogTitle,q.LogDescription,q.QuestDescription,q.AreaDescription)))>0"
        if search.isascii() and search.isdigit(): where += f' OR {qid}={int(search)}'
        where += ')'
    fields = [f"'id',{qid}", "'title',q.LogTitle", "'level',q.QuestLevel", "'category_id',q.QuestSortID", "'template_found',q.ID IS NOT NULL"]
    fields += ["'race_mask',q.AllowableRaces", "'prerequisite_race_masks',"+prerequisite_races_sql()]
    if class_id: fields += ["'class_mask',COALESCE(class_filter.AllowableClasses,0)"]
    if mode == 'active': fields += ["'status',s.status"]
    elif mode == 'completed': fields += ["'reward_record_active',s.active"]
    char_query = '' if mode == 'all' else f"""SELECT JSON_OBJECT('kind','character','guid',c.guid,'name',c.name,'level',c.level,
'race',c.race,'class',c.class,'gender',c.gender,'money',c.money) FROM acore_characters.characters c WHERE {name_filter('c',[name])};"""
    extra = ''
    if quest_id is not None:
        text_fields = ['LogDescription','QuestDescription','AreaDescription','QuestCompletionLog']
        values = ['MinLevel','QuestInfoID','SuggestedGroupNum','TimeAllowed','RequiredPlayerKills',
                  'RequiredFactionId1','RequiredFactionValue1','RequiredFactionId2','RequiredFactionValue2',
                  'RewardMoney','RewardMoneyDifficulty','RewardXPDifficulty','RewardHonor','RewardKillHonor','RewardDisplaySpell','RewardSpell',
                  'RewardTitle','RewardTalents','RewardArenaPoints','RewardNextQuest','StartItem','Flags','AllowableRaces']
        values += [f'RewardFaction{f}{i}' for i in range(1,6) for f in ('ID','Value','Override')]
        fields += [f"'{f}',q.{f}" for f in text_fields+values]
        fields += ["'special_flags',COALESCE(a.SpecialFlags,0)", "'time_allowed',q.TimeAllowed", "'player_kills',q.RequiredPlayerKills",
                   "'area',q.AreaDescription", "'money_required',GREATEST(0,-q.RewardMoney)",
                   "'faction',q.RequiredFactionId1", "'reputation_required',q.RequiredFactionValue1",
                   "'offer_text',o.RewardText", "'request_text',ri.CompletionText",
                   "'previous_quest',a.PrevQuestID", "'next_quest',a.NextQuestID", "'required_skill',a.RequiredSkillID", "'required_skill_points',a.RequiredSkillPoints",
                   "'has_area_trigger',EXISTS(SELECT 1 FROM acore_world.areatrigger_involvedrelation ar WHERE ar.quest=q.ID)"]
        origin += '''
LEFT JOIN acore_world.quest_template_addon a ON a.ID=q.ID
LEFT JOIN acore_world.quest_offer_reward o ON o.ID=q.ID
LEFT JOIN acore_world.quest_request_items ri ON ri.ID=q.ID'''
        for i in range(1,5):
            fields += [f"'target{i}',q.RequiredNpcOrGo{i}",f"'target_count{i}',q.RequiredNpcOrGoCount{i}",f"'objective_text{i}',q.ObjectiveText{i}",f"'target_name{i}',IF(q.RequiredNpcOrGo{i}>0,ct{i}.name,go{i}.name)"]
            origin += f'\nLEFT JOIN acore_world.creature_template ct{i} ON ct{i}.entry=q.RequiredNpcOrGo{i}\nLEFT JOIN acore_world.gameobject_template go{i} ON go{i}.entry=-q.RequiredNpcOrGo{i}'
        for i in range(1,7):
            fields += [f"'item_id{i}',q.RequiredItemId{i}",f"'item_count{i}',q.RequiredItemCount{i}",f"'item_name{i}',it{i}.name"]
            origin += f'\nLEFT JOIN acore_world.item_template it{i} ON it{i}.entry=q.RequiredItemId{i}'
        if mode == 'active':
            fields += ["'explored',s.explored","'timer',s.timer","'playercount',s.playercount","'money',c.money"]
            fields += [f"'mob{i}',s.mobcount{i}" for i in range(1,5)]+[f"'item{i}',s.itemcount{i}" for i in range(1,7)]
        reward_ids=[f'q.{prefix}{i}' for prefix,count in [('RewardItem',4),('RewardChoiceItemID',6)] for i in range(1,count+1)]
        detail_fields={field:field for field in ITEM_TOOLTIP_FIELDS}
        detail_fields.update({'id':'entry','level':'ItemLevel','required_level':'RequiredLevel','sell_price':'SellPrice',
                              'description':'description','required_skill':'RequiredSkill','skill_rank':'RequiredSkillRank'})
        reward_fields=','.join(f"'{key}',t.{column}" for key,column in detail_fields.items())
        extra += f"\nSELECT JSON_OBJECT('kind','reward_item',{reward_fields}) FROM acore_world.quest_template q JOIN acore_world.item_template t ON t.entry IN ({','.join(reward_ids)}) WHERE q.ID={quest_id} LIMIT 10;"
        # Fixed scalar item lookups avoid multiplying quest rows.
        for kind, entry, amount, count in [('fixed','RewardItem','RewardAmount',4),('choice','RewardChoiceItemID','RewardChoiceItemQuantity',6)]:
            for i in range(1,count+1):
                fields += [f"'{kind}_id{i}',q.{entry}{i}",f"'{kind}_count{i}',q.{amount}{i}",
                           f"'{kind}_name{i}',(SELECT t.name FROM acore_world.item_template t WHERE t.entry=q.{entry}{i})",
                           f"'{kind}_display{i}',(SELECT t.displayid FROM acore_world.item_template t WHERE t.entry=q.{entry}{i})",
                           f"'{kind}_quality{i}',(SELECT t.Quality FROM acore_world.item_template t WHERE t.entry=q.{entry}{i})"]
        for table, template, role, kind in [('creature_queststarter','creature_template','Starts','NPC'),('creature_questender','creature_template','Ends','NPC'),('gameobject_queststarter','gameobject_template','Starts','Object'),('gameobject_questender','gameobject_template','Ends','Object')]:
            extra += f"\nSELECT JSON_OBJECT('kind','contact','role','{role}','type','{kind}','id',t.entry,'name',t.name) FROM acore_world.{table} r JOIN acore_world.{template} t ON t.entry=r.id WHERE r.quest={quest_id} ORDER BY t.entry LIMIT 51;"
        extra += f"\nSELECT JSON_OBJECT('kind','contact','role','Starts','type','Item','id',t.entry,'name',t.name) FROM acore_world.item_template t WHERE t.startquest={quest_id} ORDER BY t.entry LIMIT 51;"
    count_sql = '' if quest_id is not None else f"SELECT JSON_OBJECT('kind','count','total',COUNT(*)) {origin} WHERE {where};"
    limit = 'LIMIT 1' if quest_id is not None else f'ORDER BY q.QuestSortID,q.LogTitle,{qid} LIMIT {PAGE_SIZE} OFFSET {page*PAGE_SIZE}'
    return f"""SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
{char_query}
{count_sql}
SELECT JSON_OBJECT('kind','quest',{','.join(fields)}) {origin} WHERE {where} {limit};
{extra}
COMMIT;
"""


def read_quests(sql):
    command = ['docker','exec','-i',CONTAINER,'sh','-c',
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql --user=root --default-character-set=utf8mb4 --batch --raw --skip-column-names --connect-timeout=3']
    try:
        result = subprocess.run(command,input=sql,capture_output=True,text=True,encoding='utf-8',timeout=12)
        if result.returncode or len(result.stdout)>2000000: raise ValueError('Read failed')
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        if not rows or rows[0] != {'kind':'meta','read_only':1}: raise ValueError('Read-only session unconfirmed')
        return rows[1:]
    except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
        raise DatabaseError('Cannot read saved quest data. Check Docker access and the game database.') from exc


def base_xp(level, character_level, difficulty, metadata):
    level = character_level if level == -1 else level
    values = metadata.get('xp',{}).get(str(level))
    if not values or not 0 <= difficulty < len(values): return None
    xp = max(1,min(10,2*(level-character_level)+20))*values[difficulty]//10
    step, rounding = (5,2) if xp<=100 else (10,5) if xp<=500 else (25,12) if xp<=1000 else (50,25)
    return step*((xp+rounding)//step)


class QuestLogProvider:
    def __init__(self, objective_builder, root=ROOT, reader=read_quests):
        self.objective_builder, self.reader = objective_builder, reader
        self.metadata = {}
        self.icons = {}
        for filename, attr in [('quest-metadata.json','metadata'),('item-metadata.json','icons')]:
            try:
                value = json.loads((root/'assets'/filename).read_text())
                setattr(self,attr,value if attr=='metadata' else value.get('icons',{}))
            except (OSError,ValueError): pass
        self.lock = threading.Lock()
        self.cached = {}

    def party_status(self, group, quest_id, *, watch=False):
        parameters('all', quest_id=quest_id)
        if not group:
            return {'group': None, 'quest_id': quest_id, 'characters': []}
        names = group['members']
        if watch and not names:
            return {'group':{'id':group['id'],'name':group['name']}, 'quest_id':quest_id,
                    'title':f'Quest #{quest_id}', 'allowed_classes':[], 'characters':[]}
        limit = 32 if watch else 10
        if not 1 <= len(names) <= limit:
            raise ValueError(f'Choose between 1 and {limit} characters.')
        selected = name_filter('c', names)
        sql = f"""SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
SELECT JSON_OBJECT('kind','restriction','title',q.LogTitle,'class_mask',COALESCE(a.AllowableClasses,0))
FROM acore_world.quest_template q LEFT JOIN acore_world.quest_template_addon a ON a.ID=q.ID
WHERE q.ID={quest_id} LIMIT 1;
SELECT JSON_OBJECT('kind','party_status','name',c.name,'level',c.level,'class',c.class,
'status',s.status,'rewarded',EXISTS(SELECT 1 FROM acore_characters.character_queststatus_rewarded r
WHERE r.guid=c.guid AND r.quest={quest_id}))
FROM acore_characters.characters c
LEFT JOIN acore_characters.character_queststatus s ON s.guid=c.guid AND s.quest={quest_id}
WHERE {selected} LIMIT {limit};
COMMIT;
"""
        rows = self.reader(sql)
        restriction = next((r for r in rows if r['kind']=='restriction'), {})
        class_mask = restriction.get('class_mask') or 0
        allowed_classes = [label for cid,label in CLASSES.items() if class_mask & (1 << (cid-1))] if class_mask>0 else []
        found = {r['name'].lower(): r for r in rows if r['kind']=='party_status'}
        characters = []
        for name in names:
            row = found.get(name.lower())
            status = STATUSES.get(row.get('status')) if row else None
            state = (status or ('completed' if row.get('rewarded') else 'missing')) if row else 'not_found'
            excluded = bool(row and row.get('class') and class_mask>0 and not class_mask & (1 << (row['class']-1)))
            if state == 'missing' and excluded:
                state = 'ineligible_class'
            characters.append({'name': row['name'] if row else name,
                'level': row.get('level') if row else None, 'class': row.get('class') if row else None,
                'state': state,
                'previously_completed': bool(row and row.get('rewarded'))})
        return {'group': {'id':group['id'], 'name':group['name']}, 'quest_id':quest_id,
                'title':restriction.get('title') or f'Quest #{quest_id}',
                'allowed_classes':allowed_classes, 'characters':characters}

    def get(self, mode='active', name='', search='', page=0, quest_id=None, class_id=0):
        sql = query_sql(mode,name,search,page,quest_id,class_id)
        key = (mode,name.lower() if mode!='all' else '',search,page,quest_id,class_id)
        with self.lock:
            cached = self.cached.get(key)
            if cached and time.monotonic()-cached[0]<2: return cached[1]
            rows = self.reader(sql)
            character = next((r for r in rows if r['kind']=='character'),None)
            if mode!='all' and not character: raise LookupError('No saved character found with that name.')
            quests = [dict(r) for r in rows if r['kind']=='quest']
            if quest_id is not None and not quests: raise LookupError('Quest not found in this view.')
            for q in quests:
                q['quest_side'] = quest_faction(q.get('race_mask'),q.pop('prerequisite_race_masks',None))
                q['title'] = q.get('title') or f"Quest #{q['id']}"
                category = q.get('category_id') or 0
                q['category'] = self.metadata.get('areas' if category>0 else 'sorts',{}).get(str(abs(category))) or ('Uncategorized' if not category else f'Category #{category}')
                q['state'] = STATUSES.get(q.get('status'),'unknown') if mode=='active' else 'completed' if mode=='completed' else 'catalogue'
                if quest_id is not None:
                    q['objectives'] = self.objective_builder(q) if q.get('template_found') else []
                    if mode!='active':
                        for obj in q['objectives']: obj['current'] = None
                    for obj in q['objectives']:
                        if obj['kind']=='reputation':
                            faction = self.metadata.get('factions',{}).get(str(q.get('faction')))
                            if faction: obj['label'] = f'Reputation with {faction}'
                    if q.get('RequiredFactionId2') and q.get('RequiredFactionValue2'):
                        faction = self.metadata.get('factions',{}).get(str(q['RequiredFactionId2']),f"Faction #{q['RequiredFactionId2']}")
                        q['objectives'].append({'key':'reputation2','kind':'reputation','label':f'Reputation with {faction}','required':q['RequiredFactionValue2'],'current':None,'note':'See saved quest status.'})
                    reward_details={r['id']:{k:v for k,v in r.items() if k not in ('kind','id')} for r in rows if r['kind']=='reward_item'}
                    q['rewards'] = []
                    for kind,count in [('fixed',4),('choice',6)]:
                        for i in range(1,count+1):
                            entry = q.get(f'{kind}_id{i}')
                            if entry:
                                q['rewards'].append({'kind':kind,'id':entry,'name':q.get(f'{kind}_name{i}') or f'Item #{entry}',
                                    'count':q.get(f'{kind}_count{i}'), 'quality':q.get(f'{kind}_quality{i}'),
                                    'icon':self.icons.get(str(q.get(f'{kind}_display{i}'))),**reward_details.get(entry,{})})
                    level = character['level'] if character else (q.get('level') if (q.get('level') or 0)>0 else None)
                    q['base_xp'] = base_xp(q.get('level'),level,q.get('RewardXPDifficulty') or 0,self.metadata) if level is not None and q.get('template_found') else None
                    q['reward_spells'] = [{'id':sid,'name':self.metadata.get('spells',{}).get(str(abs(sid)),f'Spell #{abs(sid)}')}
                                          for sid in dict.fromkeys([q.get('RewardDisplaySpell'),q.get('RewardSpell')]) if sid]
                    q['reputation_rewards'] = [{'id':q[f'RewardFactionID{i}'],'faction':self.metadata.get('factions',{}).get(str(q[f'RewardFactionID{i}']),f"Faction #{q[f'RewardFactionID{i}']}"),
                        'value_id':q.get(f'RewardFactionValue{i}'),'override':q.get(f'RewardFactionOverride{i}')}
                        for i in range(1,6) if q.get(f'RewardFactionID{i}')]
                    for reward in q['reputation_rewards']:
                        value = reward['value_id'] or 0
                        rep = self.metadata.get('reputation',{}).get(str(2 if value<0 else 1),[])
                        reward['base'] = reward['override']/100 if reward['override'] else rep[abs(value)] if abs(value)<len(rep) else None
            data = {'character':character,'quests':quests,'total':next((r['total'] for r in rows if r['kind']=='count'),len(quests)),
                    'page':page,'page_size':PAGE_SIZE,'mode':mode,'source':'MySQL saved quest data',
                    'refreshed_at':datetime.now(timezone.utc).isoformat()}
            if quest_id is not None:
                contacts = [r for r in rows if r['kind']=='contact']
                data['contacts'] = contacts
                data['contacts_truncated'] = any(sum(r['role']==role and r['type']==kind for r in contacts)>=51 for role,kind in [('Starts','NPC'),('Ends','NPC'),('Starts','Object'),('Ends','Object'),('Starts','Item')])
            if len(self.cached)>=64: self.cached.pop(next(iter(self.cached)))
            self.cached[key] = (time.monotonic(),data)
            return data
