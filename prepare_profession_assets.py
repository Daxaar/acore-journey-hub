#!/usr/bin/env python3
"""Read server DBC/SQL overrides into a dashboard-only professions catalogue."""
import json
from pathlib import Path
import re
from prepare_quest_assets import read_dbc
from armory import read_inventory_sql

ROOT=Path(__file__).resolve().parent


def query(select):
    return read_inventory_sql('''SET SESSION TRANSACTION READ ONLY;
SET SESSION MAX_EXECUTION_TIME=3000;
START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY;
SELECT JSON_OBJECT('kind','meta','read_only',@@SESSION.transaction_read_only);
'''+select+'\nCOMMIT;')


def signed(value):return value if value<2147483648 else value-4294967296


def icon_name(path):
    name=path.replace('\\','/').rsplit('/',1)[-1].lower()
    return name if re.fullmatch('[a-z0-9_]{1,100}',name) else None


def spell_from_dbc(row,text):
    return {'id':row[0],'name':text(row[136]),'rank':text(row[153]),'description':text(row[170]),
            'attributes':row[4],'focus':row[18],'icon_id':row[133],'effects':list(row[71:74]),'items':list(row[107:110]),
            'base':list(map(signed,row[80:83])),'die':list(map(signed,row[74:77])),
            'reagents':[(signed(row[52+i]),row[60+i]) for i in range(8) if signed(row[52+i])>0 and row[60+i]],
            'tools':[i for i in row[50:52] if i], 'tool_categories':[i for i in row[222:224] if i]}


if __name__=='__main__':
    rows,text=read_dbc('SpellIcon');icons={row[0]:icon_name(text(row[1])) for row in rows}
    rows,text=read_dbc('SkillLine')
    skills={str(r[0]):{'id':r[0],'category':signed(r[1]),'name':text(r[3]),'description':text(r[20]),'icon':icons.get(r[37])} for r in rows}
    skill_overrides=query("SELECT JSON_OBJECT('id',ID,'category',CategoryID,'name',DisplayName_Lang_enUS,'description',Description_Lang_enUS,'icon_id',SpellIconID) FROM acore_world.skillline_dbc LIMIT 1001;")
    if len(skill_overrides)>=1001:raise ValueError('Skill override limit exceeded')
    for row in skill_overrides:
        row['icon']=icons.get(row.pop('icon_id'));row['name']=row['name'] or f"Skill #{row['id']}";row['description']=row['description'] or ''
        skills[str(row['id'])]=row
    prof_ids={int(k) for k,v in skills.items() if v['category']==11 or int(k) in (129,185,356)}
    rows,_=read_dbc('SkillLineAbility');abilities={r[0]:list(r) for r in rows}
    fields=['ID','SkillLine','Spell','RaceMask','ClassMask','ExcludeRace','ExcludeClass','MinSkillLineRank',
            'SupercededBySpell','AcquireMethod','TrivialSkillLineRankHigh','TrivialSkillLineRankLow','CharacterPoints_1','CharacterPoints_2']
    overrides=query("SELECT JSON_OBJECT('row',JSON_ARRAY("+','.join(fields)+')) FROM acore_world.skilllineability_dbc LIMIT 10001;')
    if len(overrides)>=10001:raise ValueError('Skill ability override limit exceeded')
    for item in overrides:abilities[item['row'][0]]=item['row']
    prof_abilities=[r for r in abilities.values() if r[1] in prof_ids]
    spell_ids={r[2] for r in prof_abilities}
    rows,text=read_dbc('Spell');spells={r[0]:spell_from_dbc(r,text) for r in rows if r[0] in spell_ids}
    keys=[('id','ID'),('name','Name_Lang_enUS'),('rank','NameSubtext_Lang_enUS'),('description','Description_Lang_enUS'),('attributes','Attributes'),('focus','RequiresSpellFocus'),('icon_id','SpellIconID')]
    pairs=[f"'{k}',{v}" for k,v in keys]
    pairs += [f"'{key}',JSON_ARRAY("+','.join(f'{col}_{i}' for i in range(1,4))+')' for key,col in [('effects','Effect'),('items','EffectItemType'),('base','EffectBasePoints'),('die','EffectDieSides')]]
    pairs += ["'reagents',JSON_ARRAY("+','.join(f'JSON_ARRAY(Reagent_{i},ReagentCount_{i})' for i in range(1,9))+')',
              "'tools',JSON_ARRAY(Totem_1,Totem_2)","'tool_categories',JSON_ARRAY(RequiredTotemCategoryID_1,RequiredTotemCategoryID_2)"]
    for start in range(0,len(spell_ids),500):
        batch=sorted(spell_ids)[start:start+500]
        for row in query('SELECT JSON_OBJECT('+','.join(pairs)+') FROM acore_world.spell_dbc WHERE ID IN ('+','.join(map(str,batch))+');'):
            row['reagents']=[(i,n) for i,n in row['reagents'] if i>0 and n>0];row['tools']=[i for i in row['tools'] if i];row['tool_categories']=[i for i in row['tool_categories'] if i]
            spells[row['id']]=row
    recipes={};item_ids=set()
    for a in prof_abilities:
        spell=spells.get(a[2]);
        if not spell or not spell['attributes']&32 or spell['attributes']&64:continue
        skill_recipes=recipes.setdefault(str(a[1]),{})
        if str(a[2]) not in skill_recipes:
            record=dict(spell);record['icon']=icons.get(spell['icon_id']);record['abilities']=[]
            record['outputs']=[{'id':entry,'minimum':max(1,spell['base'][i]+1),'maximum':max(1,spell['base'][i]+max(1,spell['die'][i]))} for i,entry in enumerate(spell['items']) if entry and spell['effects'][i] in (24,59,157)]
            skill_recipes[str(a[2])]=record
            item_ids.update(i for i,n in spell['reagents']);item_ids.update(spell['tools']);item_ids.update(o['id'] for o in record['outputs'])
        skill_recipes[str(a[2])]['abilities'].append({'race':a[3],'class':a[4],'exclude_race':a[5],'exclude_class':a[6],'required':a[7],'acquire':a[9],'superseded':a[8],'gray':a[10],'yellow':a[11]})
    items={};icon_meta=json.loads((ROOT/'assets'/'item-metadata.json').read_text()).get('icons',{})
    for start in range(0,len(item_ids),500):
        batch=sorted(item_ids)[start:start+500]
        sql="SELECT JSON_OBJECT('id',entry,'name',name,'class',class,'subclass',subclass,'slot',InventoryType,'quality',Quality,'display',displayid,'description',description) FROM acore_world.item_template WHERE entry IN ("+','.join(map(str,batch))+');'
        for row in query(sql):row['icon']=icon_meta.get(str(row['display']));items[str(row['id'])]=row
    rows,text=read_dbc('TotemCategory');tools={str(r[0]):text(r[1]) for r in rows}
    rows,text=read_dbc('SpellFocusObject');focuses={str(r[0]):text(r[1]) for r in rows}
    result={'focuses':focuses,'skills':skills,'recipes':recipes,'items':items,'tool_categories':tools,
            'icon_names':sorted({i for i in icons.values() if i})}
    path=ROOT/'assets'/'profession-metadata.json';temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(result,ensure_ascii=False));temporary.replace(path)
    print(f"Cached {len(skills)} skills, {sum(len(v) for v in recipes.values())} recipes and {len(items)} recipe items.")
