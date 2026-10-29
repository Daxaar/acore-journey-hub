#!/usr/bin/env python3
"""Build planner effect lookups from local server DBCs and SQL overrides, read only."""
import json
from pathlib import Path
from prepare_quest_assets import read_dbc
from gear_sources import query

ROOT=Path(__file__).resolve().parent

def signed(value):return value if value<2147483648 else value-4294967296


def build():
    # Field positions match AzerothCore WotLK DBCStructure.h; no client/game files are changed.
    rows,_=read_dbc('Spell');spells={str(r[0]):{'effects':list(r[71:74]),'auras':list(r[95:98]),
        'base':list(map(signed,r[80:83])),'die':list(map(signed,r[74:77])),
        'misc':list(map(signed,r[110:113])),'scale':list(r[77:80])} for r in rows if any(r[71:74])}
    pairs=["'id',ID"]
    for key,column in [('effects','Effect'),('auras','EffectAura'),('base','EffectBasePoints'),('die','EffectDieSides'),('misc','EffectMiscValue'),('scale','EffectRealPointsPerLevel')]:
        pairs.append("'"+key+"',JSON_ARRAY("+','.join(column+'_'+str(i) for i in range(1,4))+')')
    for row in query('SELECT JSON_OBJECT('+','.join(pairs)+') FROM acore_world.spell_dbc LIMIT 10001;'):
        spells[str(row.pop('id'))]=row
    rows,_=read_dbc('SpellItemEnchantment');enchants={str(r[0]):{'types':list(r[2:5]),'amount':list(map(signed,r[5:8])),'args':list(r[11:14]),'condition':r[34]} for r in rows}
    pairs=["'id',ID","'condition',Condition_Id"]
    for key,column in [('types','Effect'),('amount','EffectPointsMin'),('args','EffectArg')]:pairs.append("'"+key+"',JSON_ARRAY("+','.join(column+'_'+str(i) for i in range(1,4))+')')
    for row in query('SELECT JSON_OBJECT('+','.join(pairs)+') FROM acore_world.spellitemenchantment_dbc LIMIT 10001;'):enchants[str(row.pop('id'))]=row
    rows,_=read_dbc('ItemRandomProperties');properties={str(r[0]):list(r[2:7]) for r in rows}
    rows,text=read_dbc('Faction');factions={str(r[0]):{'races':list(r[2:6]),'classes':list(r[6:10]),'base':list(map(signed,r[10:14]))} for r in rows}
    rows,_=read_dbc('FactionTemplate')
    templates={str(r[0]):{'faction':r[1],'group':r[3],'friendly':r[4],'hostile':r[5],'enemies':list(r[6:10]),'friends':list(r[10:14])} for r in rows}
    override_rows=query("SELECT JSON_OBJECT('id',ID,'faction',Faction,'group',FactionGroup,'friendly',FriendGroup,'hostile',EnemyGroup,'enemies',JSON_ARRAY(Enemies_1,Enemies_2,Enemies_3,Enemies_4),'friends',JSON_ARRAY(Friend_1,Friend_2,Friend_3,Friend_4)) FROM acore_world.factiontemplate_dbc LIMIT 10001;")
    if len(override_rows)>=10001:raise ValueError('Faction overrides exceed the planner limit.')
    for row in override_rows:templates[str(row.pop('id'))]=row
    rows,_=read_dbc('ChrRaces');player_factions={str(r[0]):r[2] for r in rows}
    output={'format':1,'spells':spells,'enchants':enchants,'properties':properties,'factions':factions,'faction_templates':templates,'player_factions':player_factions}
    target=ROOT/'assets'/'gear-metadata.json';target.parent.mkdir(exist_ok=True)
    temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(output,separators=(',',':')));temporary.replace(target)
    print('Prepared local planner spell, enchantment, random-property and reputation lookups.')

if __name__=='__main__':build()
