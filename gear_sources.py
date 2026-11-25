"""Planner-only, bounded read-only saved equipment and acquisition snapshots."""
from pathlib import Path
import json
from armory import read_inventory_sql
from mysql_access import name_filter, DatabaseError

ROOT=Path(__file__).resolve().parent
PREFIX='''SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
'''
ITEM_FIELDS=['entry','name','class','subclass','InventoryType','Quality','ItemLevel','RequiredLevel','AllowableClass','AllowableRace',
 'RequiredSkill','RequiredSkillRank','requiredspell','requiredhonorrank','RequiredCityRank','RequiredReputationFaction','RequiredReputationRank','bonding','Flags','FlagsExtra','maxcount',
 'ItemLimitCategory','displayid','armor','block','delay','dmg_min1','dmg_max1','dmg_min2','dmg_max2','ScalingStatDistribution','ScalingStatValue','itemset','RandomProperty','RandomSuffix','SellPrice','description','ContainerSlots','MaxDurability']
ITEM_FIELDS += [key+str(i) for i in range(1,11) for key in ('stat_type','stat_value')]
ITEM_FIELDS += [key+'_'+str(i) for i in range(1,6) for key in ('spellid','spelltrigger')]
Q_FIELDS=['ID','LogTitle','QuestLevel','MinLevel','AllowableRaces','QuestSortID','Flags','SuggestedGroupNum',
 'RequiredFactionId1','RequiredFactionValue1','RequiredFactionId2','RequiredFactionValue2']
QA_FIELDS=['AllowableClasses','PrevQuestID','MaxLevel','SpecialFlags','ExclusiveGroup','RequiredSkillID','RequiredSkillPoints',
 'RequiredMinRepFaction','RequiredMinRepValue','RequiredMaxRepFaction','RequiredMaxRepValue']


def query(sql,reader=read_inventory_sql):return reader(PREFIX+sql+'\nCOMMIT;')


def snapshot_sql(names,known_names):
    if not isinstance(names,(list,tuple)) or not 1<=len(names)<=10:raise ValueError('Choose an existing group of 1–10 characters.')
    selected=name_filter('c',names)
    trusted=tuple(dict.fromkeys([*names,*known_names]))
    if len(trusted)>352:raise ValueError('Configured character scope is too large.')
    roster=name_filter('c',trusted)
    accounts=f'SELECT sc.account FROM acore_characters.characters sc WHERE {name_filter("sc",names)}'
    scope=f'c.deleteDate IS NULL AND (c.account IN ({accounts}) OR ({roster}))'
    guilds=f'SELECT gm.guildid FROM acore_characters.guild_member gm JOIN acore_characters.characters sc ON sc.guid=gm.guid WHERE {name_filter("sc",names)}'
    return PREFIX+f'''
SELECT JSON_OBJECT('kind','character','guid',c.guid,'account',c.account,'name',c.name,'class',c.class,'race',c.race,'level',c.level,'money',c.money)
FROM acore_characters.characters c WHERE {selected};
SELECT JSON_OBJECT('kind','owner','guid',c.guid,'account',c.account,'name',c.name)
FROM acore_characters.characters c WHERE {scope} ORDER BY c.guid LIMIT 501;
SELECT JSON_OBJECT('kind','inventory','owner',c.guid,'owner_name',c.name,'account',c.account,'owner_race',c.race,
'guid',i.guid,'entry',i.itemEntry,'count',i.count,'flags',i.flags,'random',i.randomPropertyId,'enchants',i.enchantments,'bag',v.bag,'slot',v.slot,
'location',CASE WHEN v.bag=0 AND v.slot<19 THEN 'equipped' WHEN (v.bag=0 AND v.slot BETWEEN 39 AND 73) OR bankbag.item IS NOT NULL THEN 'bank' ELSE 'bags' END)
FROM acore_characters.characters c JOIN acore_characters.character_inventory v ON v.guid=c.guid
JOIN acore_characters.item_instance i ON i.guid=v.item
JOIN acore_world.item_template t ON t.entry=i.itemEntry AND t.class IN (2,4) AND t.InventoryType NOT IN (0,18)
LEFT JOIN acore_characters.character_inventory bankbag ON bankbag.guid=c.guid AND bankbag.item=v.bag AND bankbag.bag=0 AND bankbag.slot BETWEEN 67 AND 73
WHERE {scope} ORDER BY c.guid,i.guid LIMIT 12001;
SELECT JSON_OBJECT('kind','guild_item','guild',g.guildid,'guild_name',g.name,'tab',v.TabId,'slot',v.SlotId,
'guid',i.guid,'entry',i.itemEntry,'count',i.count,'flags',i.flags,'random',i.randomPropertyId,'enchants',i.enchantments)
FROM acore_characters.guild g JOIN acore_characters.guild_bank_item v ON v.guildid=g.guildid
JOIN acore_characters.item_instance i ON i.guid=v.item_guid
JOIN acore_world.item_template t ON t.entry=i.itemEntry AND t.class IN (2,4) AND t.InventoryType NOT IN (0,18)
WHERE g.guildid IN ({guilds}) ORDER BY g.guildid,i.guid LIMIT 12001;
SELECT JSON_OBJECT('kind','guild_member','guid',gm.guid,'guild',gm.guildid) FROM acore_characters.guild_member gm
JOIN acore_characters.characters c ON c.guid=gm.guid WHERE {selected};
SELECT JSON_OBJECT('kind','skill','guid',s.guid,'id',s.skill,'value',s.value) FROM acore_characters.character_skills s
JOIN acore_characters.characters c ON c.guid=s.guid WHERE {selected} LIMIT 2001;
SELECT JSON_OBJECT('kind','spell','guid',s.guid,'id',s.spell) FROM acore_characters.character_spell s
JOIN acore_characters.characters c ON c.guid=s.guid WHERE {selected} AND (s.specMask & (1 << c.activeTalentGroup))<>0 LIMIT 20001;
SELECT JSON_OBJECT('kind','rewarded','guid',s.guid,'id',s.quest,'active',s.active) FROM acore_characters.character_queststatus_rewarded s
JOIN acore_characters.characters c ON c.guid=s.guid WHERE {selected} LIMIT 20001;
SELECT JSON_OBJECT('kind','quest','guid',s.guid,'id',s.quest,'status',s.status) FROM acore_characters.character_queststatus s
JOIN acore_characters.characters c ON c.guid=s.guid WHERE {selected} LIMIT 1001;
SELECT JSON_OBJECT('kind','reputation','guid',s.guid,'id',s.faction,'standing',s.standing) FROM acore_characters.character_reputation s
JOIN acore_characters.characters c ON c.guid=s.guid WHERE {selected} LIMIT 2001;
SELECT JSON_OBJECT('kind','material','guid',c.guid,'entry',i.itemEntry,'count',SUM(i.count))
FROM acore_characters.characters c JOIN acore_characters.character_inventory v ON v.guid=c.guid
JOIN acore_characters.item_instance i ON i.guid=v.item
LEFT JOIN acore_characters.character_inventory carriedbag ON carriedbag.guid=c.guid AND carriedbag.item=v.bag AND carriedbag.bag=0 AND carriedbag.slot BETWEEN 19 AND 22
WHERE {selected} AND ((v.bag=0 AND v.slot BETWEEN 23 AND 38) OR carriedbag.item IS NOT NULL)
GROUP BY c.guid,i.itemEntry LIMIT 6001;
COMMIT;
'''


def read_snapshot(names,known_names=(),reader=read_inventory_sql):
    rows=reader(snapshot_sql(names,known_names))
    limits={'owner':501,'inventory':12001,'guild_item':12001,'skill':2001,'spell':20001,'rewarded':20001,'quest':1001,'reputation':2001,'material':6001}
    for kind,limit in limits.items():
        if sum(r['kind']==kind for r in rows)>=limit:
            raise DatabaseError('Planner snapshot exceeds its '+kind+' limit; no partial equipment comparison was displayed.')
    return rows


def read_items(ids,reader=read_inventory_sql):
    ids=sorted(set(int(i) for i in ids if int(i)>0));result={}
    if len(ids)>40000:raise DatabaseError('Item catalogue exceeds the planner limit.')
    for start in range(0,len(ids),500):
        batch=','.join(map(str,ids[start:start+500]))
        sql="SELECT JSON_OBJECT('kind','template','v',JSON_ARRAY("+','.join('t.'+f for f in ITEM_FIELDS)+')) FROM acore_world.item_template t WHERE t.entry IN ('+batch+');'
        for row in query(sql,reader):
            item=dict(zip(ITEM_FIELDS,row['v']));result[item['entry']]=item
    return result


def read_sources(level_cap,reader=read_inventory_sql):
    if type(level_cap)is not int or not 1<=level_cap<=90:raise ValueError('Invalid planner level window.')
    rewards=[f'q.RewardItem{i}' for i in range(1,5)]+[f'q.RewardChoiceItemID{i}' for i in range(1,7)]
    fields=[f'q.{f}' for f in Q_FIELDS]+[f'COALESCE(a.{f},0)' for f in QA_FIELDS]
    fields += [f'JSON_ARRAY('+','.join(rewards)+')', 'COALESCE(p.AllowableRaces,0)','COALESCE(pa.AllowableClasses,0)',
      'EXISTS(SELECT 1 FROM acore_world.conditions co WHERE co.SourceTypeOrReferenceId=19 AND co.SourceEntry=q.ID)']
    quests=[];last=0
    for _ in range(30):
        sql="SELECT JSON_OBJECT('kind','qsource','v',JSON_ARRAY("+','.join(fields)+f''')) FROM acore_world.quest_template q
LEFT JOIN acore_world.quest_template_addon a ON a.ID=q.ID
LEFT JOIN acore_world.quest_template p ON p.ID=ABS(a.PrevQuestID)
LEFT JOIN acore_world.quest_template_addon pa ON pa.ID=p.ID
WHERE q.ID>{last} AND q.MinLevel<={level_cap} AND (q.Flags & 16384)=0
AND UPPER(q.LogTitle) NOT REGEXP '<[[:space:]]*(UNUSED|DEPRECATED|NYI)[[:space:]]*>'
AND EXISTS(SELECT 1 FROM acore_world.item_template it WHERE it.entry IN ({','.join(rewards)}) AND it.class IN (2,4) AND it.InventoryType NOT IN (0,4,18,19) AND it.RequiredLevel<={level_cap})
ORDER BY q.ID LIMIT 1500;'''
        rows=query(sql,reader)
        for row in rows:
            q=dict(zip([*Q_FIELDS,*QA_FIELDS,'rewards','prev_race','prev_class','conditions'],row['v']));quests.append(q)
        if len(rows)<1500:break
        last=quests[-1]['ID']
    else:raise DatabaseError('Quest source catalogue exceeds the planner limit.')
    vendor_sql=f'''SELECT JSON_OBJECT('kind','vendor','entry',v.item,'npc',c.entry,'name',c.name,'faction',c.faction,'cost',t.BuyPrice,'buy_count',t.BuyCount,
'extended',v.ExtendedCost,'stock',v.maxcount,'map',sp.map,'x',sp.position_x,'y',sp.position_y)
FROM acore_world.npc_vendor v JOIN acore_world.item_template t ON t.entry=v.item
JOIN acore_world.creature_template c ON c.entry=v.entry
LEFT JOIN (SELECT id,MIN(guid) AS guid FROM acore_world.creature GROUP BY id) first_spawn ON first_spawn.id=c.entry
LEFT JOIN acore_world.creature sp ON sp.guid=first_spawn.guid
WHERE t.class IN (2,4) AND t.InventoryType NOT IN (0,4,18,19) AND t.RequiredLevel<={level_cap}
ORDER BY v.entry,v.item LIMIT 15001;'''
    vendors=query(vendor_sql,reader)
    if len(vendors)>=15001:raise DatabaseError('Vendor catalogue exceeds the planner limit.')
    return quests,vendors


def read_dungeon_sources(level_cap, reader=read_inventory_sql):
    from prepare_quest_assets import read_dbc

    maps, text = read_dbc('Map')
    names = {row[0]: text(row[5]) for row in maps if row[2] == 1 and text(row[5])}
    encounters, _ = read_dbc('DungeonEncounter')
    lfg, _ = read_dbc('LFGDungeons')
    minimums = {}
    for row in lfg:
        key = (row[23], row[24])
        if row[18]:
            minimums[key] = min(minimums.get(key, row[18]), row[18])
    records = [[row[0], row[1], row[2], minimums.get((row[1], row[2]))]
               for row in encounters if row[1] in names and row[2] in (0, 1)]
    catalog = json.dumps(records, separators=(',', ':'))
    rows = query(f"""
WITH RECURSIVE boss AS (
    SELECT d.map_id,d.difficulty,e.creditEntry AS npc,t.name,
           COALESCE(h.lootid,t.lootid) AS loot,
           COALESCE(NULLIF(a.min_level,0),d.lfg_min,IF(d.difficulty=1,80,NULL)) AS min_level
    FROM JSON_TABLE('{catalog}', '$[*]' COLUMNS(encounter INT PATH '$[0]',
      map_id INT PATH '$[1]',difficulty INT PATH '$[2]',lfg_min INT PATH '$[3]')) d
    JOIN acore_world.instance_encounters e ON e.entry=d.encounter AND e.creditType=0
    JOIN acore_world.creature_template t ON t.entry=e.creditEntry
    LEFT JOIN acore_world.creature_template h ON d.difficulty=1 AND h.entry=t.difficulty_entry_1
    LEFT JOIN acore_world.dungeon_access_template a ON a.map_id=d.map_id AND a.difficulty=d.difficulty
    WHERE COALESCE(NULLIF(a.min_level,0),d.lfg_min,IF(d.difficulty=1,80,NULL))<={level_cap}
), drops AS (
    SELECT b.map_id,b.difficulty,b.npc,b.name,b.min_level,l.Item,l.Reference,
           CASE WHEN l.Reference>0 THEN l.GroupId ELSE 0 END AS ref_group,0 AS depth
    FROM boss b JOIN acore_world.creature_loot_template l ON l.Entry=b.loot
    WHERE l.QuestRequired=0 AND (l.LootMode & 1)<>0
    UNION ALL
    SELECT d.map_id,d.difficulty,d.npc,d.name,d.min_level,l.Item,l.Reference,
           CASE WHEN l.Reference>0 THEN l.GroupId ELSE 0 END,d.depth+1
    FROM drops d JOIN acore_world.reference_loot_template l ON l.Entry=d.Reference
    WHERE d.Reference>0 AND d.depth<8 AND l.QuestRequired=0 AND (l.LootMode & 1)<>0
      AND (d.ref_group=0 OR l.GroupId=d.ref_group)
)
SELECT JSON_OBJECT('entry',x.Item,'map',x.map_id,'difficulty',x.difficulty,
                   'npc',x.npc,'name',x.name,'min_level',x.min_level)
FROM (SELECT DISTINCT d.Item,d.map_id,d.difficulty,d.npc,d.name,d.min_level FROM drops d
      JOIN acore_world.item_template t ON t.entry=d.Item
      WHERE d.Reference=0 AND t.class IN (2,4) AND t.InventoryType NOT IN (0,4,18,19)
        AND t.RequiredLevel<={level_cap}) x LIMIT 15001;
""", reader)
    if len(rows) >= 15001:
        raise DatabaseError('Dungeon loot catalogue exceeds the planner limit.')
    for row in rows:
        row['dungeon'] = names[row['map']]
    return rows


def load_json(name,root=ROOT):
    try:
        value=json.loads((root/'assets'/name).read_text())
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}
