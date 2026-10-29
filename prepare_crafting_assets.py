#!/usr/bin/env python3
"""Build a reproducible local Classic catalogue; only bounded read-only game queries.

Run prepare_profession_assets.py first. The public Classic DB is used solely as an
era-membership reference, never imported into any database. Generated data stays local.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import urllib.request

from crafting import PROFESSIONS, fingerprint
from crafting_assessments import apply_panel
from gear_sources import query
from deployment_config import container

ROOT = Path(__file__).resolve().parent
ERA_COMMIT = '603ece109099ce44a5447a1b1cffd65c7272d71c'
ERA_URL = f'https://raw.githubusercontent.com/cmangos/classic-db/{ERA_COMMIT}/Full_DB/ClassicDB_1_12_1_z2815.sql.gz'
ERA_SHA = '4f92db520868ab4e566726f68b5b2e380ae781209beaf22237b4f7f04600d0c0'
METHOD_VERSION = 'classic-availability-pareto-v1'


def sql_rows(line):
    """Parse mysqldump VALUES without executing SQL; respect escaped quoted commas."""
    body = line.split(' VALUES ',1)[1]
    row=[]; token=[]; quoted=False; escaped=False; active=False
    for c in body:
        if escaped: token.append(c); escaped=False; continue
        if quoted and c=='\\': escaped=True; continue
        if c=="'": quoted=not quoted; continue
        if not quoted:
            if c=='(':
                active=True; row=[]; token=[]; continue
            if c in ',)' and active:
                row.append(''.join(token));token=[]
                if c==')': yield row;active=False
                continue
        if active: token.append(c)


def classic_items(path):
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ERA_SHA: raise ValueError('Classic reference checksum mismatch')
    result={}
    with gzip.open(path,'rt') as stream:
        for line in stream:
            if line.startswith('INSERT INTO `item_template` VALUES '):
                for row in sql_rows(line): result[int(row[0])]={'name':row[3]}
    if len(result)<10000: raise ValueError('Classic reference is incomplete')
    return result


def limited(sql, limit=20001):
    rows=query(sql+f' LIMIT {limit};')
    if len(rows)>=limit: raise ValueError('Source query exceeded limit; partial data refused')
    return rows


def item_type(item):
    if item['class']==2: return 'weapon'
    return {1:'cloth',2:'leather',3:'mail',4:'plate',6:'shield'}.get(item['subclass'],'other')


def stats(item):
    """Dimensions, never a total score. Separate primary stats, armor and damage."""
    out=defaultdict(float)
    for i in range(1,11):
        if item.get('stat_value'+str(i)): out['stat:'+str(item['stat_type'+str(i)])]+=item['stat_value'+str(i)]
    if item.get('armor'): out['armor']=item['armor']
    if item.get('block'): out['block']=item['block']
    for key in ('holy_res','fire_res','nature_res','frost_res','shadow_res','arcane_res'):
        if item.get(key):out[key]=item[key]
    if item.get('delay'):out['dps']=(item['dmg_min1']+item['dmg_max1']+item['dmg_min2']+item['dmg_max2'])*500/item['delay']
    return dict(out)


def complex_item(item):
    return bool(item['RandomProperty'] or item['RandomSuffix'] or item['itemset'] or item['ScalingStatDistribution'] or item.get('socketColor_1') or
                any(item.get('spellid_'+str(i)) for i in range(1,6)))


def dominates(a,b):
    keys=set(a)|set(b)
    return all(a.get(k,0)>=b.get(k,0) for k in keys) and any(a.get(k,0)>b.get(k,0) for k in keys)


def availability(item, recipes):
    # These are explicit calibration hypotheses, not skill/5 or equip-level claims.
    skill=min(r['required_skill'] for r in recipes)
    training_low, training_high = ((5,15) if skill<=75 else (10,25) if skill<=150 else (20,40) if skill<=225 else (35,60))
    train=[s['level'] for r in recipes for s in r['sources'] if s['kind']=='trainer' and s['level']]
    lower=max(1,item['RequiredLevel'],training_low,min(train) if train else 1)
    unresolved=any(not r['sources'] or r['recipe_items'] or r['skill_conflict'] or any(s['kind'] not in ('trainer','vendor','quest') for s in r['sources']) or
                   r['specialization'] for r in recipes)
    upper=max(lower,training_high)
    if unresolved:upper=60
    return {'low':min(60,lower),'high':min(60,upper),'confidence':'low' if unresolved else 'medium',
            'scenario':'self-sufficient',
            'assumptions':'Ordinary leveling and profession investment, no higher-level funding. Skill tiers use explicit level bands (1–75: 5–15; 76–150: 10–25; 151–225: 20–40; 226–300: 35–60), not a skill/5 formula. Recipe travel, prerequisites, reputation, rare materials and local economy need review.',
            'material_effort':'Quantities are unchanged. Intermediate crafts and cross-profession purchases may be required; no drop-rate or gold-cost estimate is asserted.',
            'scenarios':[{'name':'self-sufficient','low':min(60,lower),'high':min(60,upper),'confidence':'low' if unresolved else 'medium'},
                         {'name':'trading','low':max(1,item['RequiredLevel']),'high':None,'confidence':'low','assumption':'Market supply, travel and budget unverified; equip level is only a lower bound.'},
                         {'name':'higher-level support','low':max(1,item['RequiredLevel']),'high':None,'confidence':'low','assumption':'Assumes a qualified crafter, accessible recipe and supplied materials; binding and wear requirements still apply.'}]}


def build(root, era_path):
    started=datetime.now(timezone.utc).isoformat()
    era=classic_items(era_path)
    metadata_path=root/'assets'/'profession-metadata.json'
    metadata=json.loads(metadata_path.read_text())
    # A fresh DBC/override extraction is a prerequisite, not silently substituted.
    if not all(str(p) in metadata['recipes'] for p in PROFESSIONS):raise ValueError('Missing profession metadata')
    candidates=defaultdict(list); excluded=[]
    for skill in PROFESSIONS:
        for recipe in metadata['recipes'][str(skill)].values():
            for output in recipe.get('outputs',[]):
                item=metadata['items'].get(str(output['id']),{})
                if item.get('class') not in (2,4) or item.get('slot',0) in (0,18,24,27):continue
                if output['id'] not in era:
                    excluded.append({'id':output['id'],'spell':recipe['id'],'reason':'Absent from pinned Classic reference; later-era or unresolved. No required-level inference.'});continue
                candidates[output['id']].append((skill,recipe))
    # Full templates preserve baseline fields; no balancing data is written to MySQL.
    all_ids=limited("SELECT JSON_OBJECT('id',entry) FROM acore_world.item_template WHERE class IN (2,4) AND InventoryType NOT IN (0,18,24,27) AND RequiredLevel<=60 ORDER BY entry")
    ids={r['id'] for r in all_ids if r['id'] in era}
    columns=[r['name'] for r in query("SELECT JSON_OBJECT('name',COLUMN_NAME) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='acore_world' AND TABLE_NAME='item_template' ORDER BY ORDINAL_POSITION LIMIT 250;")]
    if not columns or len(columns)>=250 or any(not re.fullmatch('[A-Za-z0-9_]+',c) for c in columns):raise ValueError('Unexpected item schema')
    templates={}
    all_entries=sorted(ids|set(candidates))
    for start in range(0,len(all_entries),400):
        batch=','.join(map(str,all_entries[start:start+400]))
        rows=query("SELECT JSON_OBJECT('values',JSON_ARRAY("+','.join('`'+c+'`' for c in columns)+f')) FROM acore_world.item_template WHERE entry IN ({batch}) ORDER BY entry LIMIT 401;')
        for row in rows:
            item=dict(zip(columns,row['values']));templates[item['entry']]=item
    # Teaching recipe items encode the learned spell in spellid_2 (with a learn trigger).
    taught=defaultdict(list)
    recipe_rows=limited("SELECT JSON_OBJECT('id',entry,'name',name,'spell',spellid_2,'skill',RequiredSkillRank,'bonding',bonding,'reputation',RequiredReputationFaction,'rank',RequiredReputationRank) FROM acore_world.item_template WHERE class=9 AND spellid_2>0 ORDER BY entry")
    for row in recipe_rows:taught[row['spell']].append(row)
    trainers=defaultdict(list)
    for row in limited("SELECT JSON_OBJECT('spell',SpellId,'trainer',TrainerId,'level',ReqLevel,'skill',ReqSkillRank,'cost',MoneyCost,'ability',JSON_ARRAY(ReqAbility1,ReqAbility2,ReqAbility3)) FROM acore_world.trainer_spell ORDER BY TrainerId,SpellId"):
        trainers[row['spell']].append({'kind':'trainer',**row})
    for row in limited("SELECT JSON_OBJECT('spell',SpellID,'trainer',ID,'level',ReqLevel,'skill',ReqSkillRank,'cost',MoneyCost,'ability',JSON_ARRAY(ReqSpell)) FROM acore_world.npc_trainer WHERE SpellID>0 ORDER BY ID,SpellID"):
        trainers[row['spell']].append({'kind':'trainer',**row})
    # Index source families once. Resolve nested reference-loot paths conservatively.
    vendors=limited("SELECT JSON_OBJECT('item',item,'npc',entry,'stock',maxcount,'restock',incrtime,'extended_cost',ExtendedCost) FROM acore_world.npc_vendor ORDER BY item,entry",50001)
    source_map=defaultdict(list)
    for row in vendors:source_map[row['item']].append({'kind':'vendor',**row})
    for row in limited("SELECT JSON_OBJECT('id',ID,'name',LogTitle,'level',QuestLevel,'minimum',MinLevel,'items',JSON_ARRAY(RewardItem1,RewardItem2,RewardItem3,RewardItem4,RewardChoiceItemID1,RewardChoiceItemID2,RewardChoiceItemID3,RewardChoiceItemID4,RewardChoiceItemID5,RewardChoiceItemID6),'spells',JSON_ARRAY(RewardSpell,RewardDisplaySpell)) FROM acore_world.quest_template ORDER BY ID"):
        for entry in set(row.pop('items'))-{0}:source_map[entry].append({'kind':'quest',**row})
        for spell in set(row['spells'])-{0}:trainers[spell].append({'kind':'quest','id':row['id'],'name':row['name'],'level':row['minimum']})
    # Build material/recipe rarity evidence from direct loot and reference edges.
    refs=defaultdict(set)
    loot_roots=defaultdict(list)
    for row in limited("SELECT JSON_OBJECT('entry',Entry,'item',Item,'reference',Reference) FROM acore_world.reference_loot_template ORDER BY Entry,Item",40001):
        if row['item']:source_map[row['item']].append({'kind':'reference loot','id':row['entry']})
        if row['reference']:refs[abs(row['reference'])].add(row['entry'])
    # Preserve full source identities; reference nesting remains explicitly conditional.
    creatures=defaultdict(list)
    for row in limited("SELECT JSON_OBJECT('id',entry,'loot',lootid,'name',name,'minimum',minlevel,'maximum',maxlevel,'rank',`rank`,'faction',faction) FROM acore_world.creature_template WHERE lootid>0 ORDER BY entry",50001):
        creatures[row['loot']].append(row)
    for table in ('creature_loot_template','gameobject_loot_template','item_loot_template','fishing_loot_template','skinning_loot_template'):
        last=0
        # Keyset by entry; each page includes all rows for up to 2000 entry groups.
        for _ in range(100):
            entries=query(f"SELECT JSON_OBJECT('id',Entry) FROM acore_world.{table} WHERE Entry>{last} GROUP BY Entry ORDER BY Entry LIMIT 2000;")
            if not entries:break
            top=entries[-1]['id']
            rows=limited(f"SELECT JSON_OBJECT('entry',Entry,'item',Item,'reference',Reference,'chance',Chance) FROM acore_world.{table} WHERE Entry>{last} AND Entry<={top} ORDER BY Entry,Item",50001)
            for row in rows:
                if row['reference']:
                    if table=='creature_loot_template':
                        for creature in creatures.get(row['entry'],[]):
                            loot_roots[abs(row['reference'])].append({'kind':'creature loot','id':creature['id'],'name':creature['name'],'level':creature['minimum'],'maximum':creature['maximum'],'rank':creature['rank'],'loot_entry':row['entry']})
                    else:
                        loot_roots[abs(row['reference'])].append({'kind':table.replace('_loot_template','')+' loot','id':row['entry'],'id_type':'loot entry'})
                if row['item']:
                    if table=='creature_loot_template':
                        for creature in creatures.get(row['entry'],[]):
                            source_map[row['item']].append({'kind':'creature loot','id':creature['id'],'name':creature['name'],'level':creature['minimum'],'maximum':creature['maximum'],'rank':creature['rank'],'loot_entry':row['entry'],'chance':row['chance']})
                    else:
                        source_map[row['item']].append({'kind':table.replace('_loot_template','')+' loot','id':row['entry'],'chance':row['chance'],'id_type':'loot entry'})
            last=top
            if len(entries)<2000:break
        else:raise ValueError('Loot source paging limit exceeded; partial data refused')
    def reference_sources(entry,seen=()):
        if entry in seen or len(seen)>=32:return [{'kind':'unresolved reference cycle/depth','id':entry}]
        result=[{**s,'via_reference':list(seen)+( [entry] )} for s in loot_roots.get(entry,[])]
        for parent in sorted(refs.get(entry,[])):
            result.extend(reference_sources(parent,(*seen,entry)))
        if len(result)>10000:raise ValueError('Reference-loot expansion limit exceeded')
        return result
    reference_cache={}
    source_counts={}
    for entry,paths in list(source_map.items()):
        resolved=[]
        for source in paths:
            if source['kind']=='reference loot':
                if source['id'] not in reference_cache:reference_cache[source['id']]=reference_sources(source['id'])
                resolved.extend(reference_cache[source['id']])
        # Stable de-duplication retains paths and never treats raw chance as effective probability.
        paths.extend({**s,'chance_note':'Nested/group loot: effective probability not computed'} for s in resolved)
        source_counts[entry]=len(paths)
        # Retain bounded evidence for each source family; raw tables are reproducible,
        # not duplicated as a game-data dump in the dashboard catalogue.
        families=defaultdict(list)
        for source in paths:families[source['kind']].append(source)
        sample=[]
        for kind in sorted(families):
            sample.extend(sorted(families[kind],key=lambda s:(s.get('level',s.get('minimum',0)),s.get('id',s.get('npc',0))))[:24])
        paths[:]=sample
    intermediate=defaultdict(list)
    for skill,skill_recipes in metadata['recipes'].items():
        for recipe in skill_recipes.values():
            for output in recipe.get('outputs',[]):
                intermediate[output['id']].append({'profession':int(skill),'spell':recipe['id'],'name':recipe['name'],'reagents':recipe['reagents']})
    def material_record(entry,count,seen=()):
        paths=source_map.get(entry,[])
        available_levels=[s['level'] for s in paths if s['kind']=='creature loot' and s.get('rank')==0]
        crafts=intermediate.get(entry,[])
        result={'id':entry,'name':metadata['items'].get(str(entry),{}).get('name',f'Item #{entry}'),'count':count,'sources':paths[:24],'source_count':source_counts.get(entry,len(paths)),
                'effort':{'classification':'crafted intermediate / cross-profession input' if crafts else 'vendor input' if any(s['kind']=='vendor' for s in paths) else 'gathered or dropped input' if paths else 'unresolved',
                          'observed_nonelite_creature_levels':[min(available_levels),max(available_levels)] if available_levels else None,
                          'confidence':'low','note':'Creature levels describe source evidence, not guaranteed acquisition. Gathering, node access, economy and effective drop rates require review.'},
                'intermediate_recipes':[]}
        if entry in seen or len(seen)>=4:
            result['effort']['note']+=' Intermediate expansion stopped at cycle/depth boundary.'
        else:
            for craft in crafts[:4]:
                result['intermediate_recipes'].append({'profession':craft['profession'],'spell':craft['spell'],'name':craft['name'],
                    'inputs':[material_record(i,n,(*seen,entry)) for i,n in craft['reagents']]})
        return result
    records=[]
    for entry,pairs in sorted(candidates.items()):
        item=templates.get(entry)
        if not item or not 0<=item['RequiredLevel']<=60:
            excluded.append({'id':entry,'reason':'Missing live template or outside level scope'});continue
        recipes=[]
        for skill,r in pairs:
            sources=list(trainers.get(r['id'],[]))
            recipe_items=[]
            for book in taught.get(r['id'],[]):
                paths=source_map.get(book['id'],[])
                recipe_items.append({**book,'sources':paths[:24],'source_count':source_counts.get(book['id'],len(paths))})
                sources.extend({**s,'recipe_item':book['id']} for s in paths)
            dbc_skill=min(a['required'] for a in r['abilities'])
            actual_skills=[s['skill'] for s in sources if s['kind']=='trainer' and s.get('skill',0)>0]+[b['skill'] for b in recipe_items if b['skill']>0]
            actual_skill=min(actual_skills) if actual_skills else dbc_skill
            recipes.append({'id':r['id'],'name':r['name'],'profession':skill,'required_skill':max(dbc_skill,actual_skill),
                            'dbc_skill':dbc_skill,'learning_skill':actual_skill,'skill_conflict':dbc_skill>actual_skill,
                            'abilities':r['abilities'],'specialization':any(any(s.get('ability',[])) for s in sources),
                            'sources':sources[:24],'source_count':len(sources),'recipe_items':recipe_items,'focus':metadata['focuses'].get(str(r['focus']),''),
                            'tools':r['tools'],'tool_categories':r['tool_categories'],
                            'reagents':[material_record(i,n) for i,n in r['reagents']]})
        avail=availability(item,recipes)
        record={'id':entry,'name':item['name'],'slot':item['InventoryType'],'quality':item['Quality'],'type':item_type(item),
                'era':{'name':'Classic','evidence':'Present in pinned CMaNGOS Classic 1.12 database; not inferred from equip level','reference_name':era[entry]['name']},
                'scope':'endgame' if item['RequiredLevel']==60 or (item['ItemLevel']>=60 and min(r['required_skill'] for r in recipes)>=300) else 'initial' if item['RequiredLevel']<=30 else 'future',
                'baseline':item,'proposed':dict(item),'recipes':recipes,'availability':avail,'comparators':[],
                'assessment':'manual review','reasoning':[],'limitations':[]}
        # Candidate pool uses acquisition band, same armor/weapon subclass and slot.
        pool=[]
        base_stats=stats(item)
        for other in templates.values():
            if other['entry']==entry or other['InventoryType']!=item['InventoryType'] or other['class']!=item['class'] or other['subclass']!=item['subclass']:continue
            if other['Quality']>3 or other['requiredhonorrank'] or other['RequiredReputationFaction']:continue
            if not max(1,avail['low']-5)<=max(1,other['RequiredLevel'])<=min(60,avail['high']):continue
            sources=source_map.get(other['entry'],[])
            # Keep genuine acquisition evidence; don't claim unavailable DB templates are obtainable.
            concrete=[s for s in sources if s['kind'] in ('vendor','quest','creature loot','gameobject loot')]
            concrete=[s for s in concrete if not (s['kind']=='quest' and (s['minimum']>avail['high'] or s['level']>avail['high'])) and not (s['kind']=='creature loot' and s['level']>avail['high'])]
            if not concrete:continue
            compatible=(item['AllowableClass']==other['AllowableClass'] and item['AllowableRace']==other['AllowableRace'])
            v=stats(other)
            simple=not complex_item(item) and not complex_item(other) and compatible and not item['requiredspell'] and not other['requiredspell'] and item['delay']==other['delay'] and item['dmg_type1']==other['dmg_type1'] and item['dmg_type2']==other['dmg_type2']
            # Conditional Pareto relation: never a total-stat rank or effect estimate.
            relation='alternative'
            if simple:
                relation='crafted dominates' if dominates(base_stats,v) else 'comparator dominates' if dominates(v,base_stats) else 'trade-off or equal'
            pool.append({'id':other['entry'],'name':other['name'],'baseline':other,'stats':v,'sources':concrete[:24],'source_count':len(concrete),
                         'relation':relation,'conditional':True,'availability_note':'Source exists; faction, quest chain, drop effort, travel and market access require manual verification.'})
        pool.sort(key=lambda o:(abs(max(1,o['baseline']['RequiredLevel'])-avail['low']),o['id']))
        # Prefer a balanced panel of distinct relations, with no hidden total-score sort.
        chosen=[]
        for relation in ('comparator dominates','crafted dominates','trade-off or equal','alternative'):
            chosen.extend([p for p in pool if p['relation']==relation][:3])
        record['comparators']=chosen
        record['comparison_pool_size']=len(pool)
        record['reasoning']=[f"Compared {len(pool)} same-slot/subclass Classic alternatives in acquisition band {avail['low']}–{avail['high']}; source availability is conditional."]
        if complex_item(item):record['limitations'].append('Proc/use spell, random suffix/property, scaling or set bonus requires specialist evaluation; no flat-stat conclusion.')
        record['limitations'].extend(['Recipe/material availability is an explicit scenario estimate, not a measured leveling guarantee.',
                                     'Source panels display at most 24 rows per input/alternative with total row counts. Reference paths are resolved but vendor faction/reputation, quests and specialization access need manual validation. No source chance is an effective drop probability.',
                                     'No combat simulation or owner in-game acceptance.'])
        better=[p for p in pool if p['relation']=='comparator dominates']
        wins=[p for p in pool if p['relation']=='crafted dominates']
        resolved=[p for p in pool if p['relation']!='alternative']
        if not complex_item(item) and resolved and not better and any(stats(item).values()) and item['InventoryType'] not in (4,19):
            record['assessment']='strong — leave unchanged' if len(wins)>=3 else 'competitive — leave unchanged'
            record['reasoning'].append('Conditional flat-stat screening found no dominating alternative. Retain baseline; effects and acquisition assumptions remain reviewable.')
        elif better:
            record['reasoning'].append('At least one conditional alternative dominates the resolved dimensions. This flags an investigation; acquisition and role evidence determine whether an adjustment is warranted. No change is applied to game data.')
        else:record['reasoning'].append('Insufficient resolved comparable evidence; retain baseline and request manual review.')
        apply_panel(record)
        record['initial_candidate_ready_for_review']=bool(record['scope']=='initial' and record['assessment']=='adjustment proposed' and avail['high']<=30 and avail['confidence']=='medium')
        record['fingerprint']=fingerprint(record)
        records.append(record)
    runtime={}
    for kind in ('world_container','db_container'):
        result=subprocess.run(['docker','inspect','--format','{"image_id":{{json .Image}},"image_tag":{{json .Config.Image}}}',container(kind)],capture_output=True,text=True,timeout=10,check=True)
        runtime[kind]=json.loads(result.stdout)
    nearby_sources={}
    for label,path in [('core',root.parent/'acore-playerbots'),('playerbots',root.parent/'acore-playerbots/modules/mod-playerbots')]:
        if (path/'.git').exists():
            result=subprocess.run(['git','-C',str(path),'rev-parse','HEAD'],capture_output=True,text=True,timeout=10)
            if result.returncode==0 and re.fullmatch('[a-f0-9]{40}',result.stdout.strip()):nearby_sources[label]=result.stdout.strip()
    provenance={'generated_at':datetime.now(timezone.utc).isoformat(),'extraction_started':started,'method':METHOD_VERSION,
                'runtime_images':runtime,'nearby_source_commits_not_runtime_attestation':nearby_sources,
                'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'authored_assessments_sha256':hashlib.sha256((root/'crafting_assessments.py').read_bytes()).hexdigest(),
                'era_source':ERA_URL,'era_commit':ERA_COMMIT,'era_sha256':ERA_SHA,'era_item_count':len(era),
                'profession_metadata_sha256':hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
                'environment':'Configured server read-only extraction; other servers unverified',
                'baseline_sha256':fingerprint({str(k):v for k,v in sorted(templates.items())}),
                'schema_fields':columns,'excluded_count':len(excluded),'record_count':len(records),
                'limitations':['Pinned Classic full database is an era-membership reference; later update additions may be absent and remain unresolved.',
                               'Catalogue stats are current server WotLK baseline, not original Vanilla stats.','Screening findings are provisional engineering assessments; all owner review decisions start not reviewed.']}
    output={'format':1,'provenance':provenance,'records':records,'excluded':excluded}
    p=root/'assets'/'crafting-catalogue.json';p.parent.mkdir(exist_ok=True)
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(output,ensure_ascii=False,separators=(',',':')));tmp.replace(p)
    print(f'Catalogue: {len(records)} Classic equippables; {len(excluded)} excluded/unresolved outputs. Dataset {hashlib.sha256(p.read_bytes()).hexdigest()}')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--classic-reference',type=Path,help='Previously downloaded, checksum-verified .sql.gz reference')
    args=parser.parse_args()
    path=args.classic_reference or ROOT/'assets'/'classic-era-reference.sql.gz'
    if not path.exists():
        if args.classic_reference:parser.error('Reference file does not exist')
        path.parent.mkdir(exist_ok=True)
        data=urllib.request.urlopen(ERA_URL,timeout=60).read()
        if hashlib.sha256(data).hexdigest()!=ERA_SHA:raise ValueError('Reference checksum mismatch')
        path.write_bytes(data)
    build(ROOT,path)


if __name__=='__main__':main()
