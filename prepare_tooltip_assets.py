#!/usr/bin/env python3
"""Prepare spell/glyph tooltip text from server DBCs and read-only SQL overrides."""
import argparse
import json
import re
import struct
from pathlib import Path
from prepare_quest_assets import read_dbc
from prepare_profession_assets import query,signed,icon_name

ROOT=Path(__file__).resolve().parent


def bounded_query(sql,limit=10001):
    rows=query(sql)
    if len(rows)>=limit:raise ValueError('Tooltip override table exceeds the supported limit')
    return rows


def prepare(metadata_path,output):
    metadata=json.loads(Path(metadata_path).read_text())
    rows,text=read_dbc('SpellIcon');icons={r[0]:icon_name(text(r[1])) for r in rows}
    rows,text=read_dbc('Spell')
    spells={r[0]:{'id':r[0],'name':text(r[136]),'rank':text(r[153]),'icon':icons.get(r[133]),'icon_id':r[133],
                    'attributes':r[4],'power_type':signed(r[41]),'cost':r[42],'cost_per_level':r[43],'cost_percent':r[204],
                    'recovery':r[29],'category_recovery':r[30],'description':text(r[170]),'cast':r[28],'duration':r[40],'range':r[46],'chain':list(r[104:107]),'radius':list(r[92:95]),
                    'effects':list(r[71:74]),'base':list(map(signed,r[80:83])),'die':list(map(signed,r[74:77])),
                    'per_level':[struct.unpack('<f',struct.pack('<I',v))[0] for v in r[77:80]],'period':list(r[98:101]),'misc':list(map(signed,r[110:113])),'triggers':list(r[116:119]),
                    'proc_chance':r[35],'stacks':r[49]} for r in rows}
    rows,_=read_dbc('GlyphProperties');glyphs={str(r[0]):{'spell':r[1],'flags':r[2]} for r in rows}
    for r in bounded_query("SELECT JSON_OBJECT('id',ID,'spell',SpellID,'flags',GlyphSlotFlags) FROM acore_world.glyphproperties_dbc LIMIT 10001;"):
        glyphs[str(r['id'])]={'spell':r['spell'],'flags':r['flags']}
    rows,_=read_dbc('SpellCastTimes');casts={str(r[0]):signed(r[1]) for r in rows}
    for r in bounded_query("SELECT JSON_OBJECT('id',ID,'base',Base) FROM acore_world.spellcasttimes_dbc LIMIT 10001;"):casts[str(r['id'])]=r['base']
    rows,_=read_dbc('SpellDuration');durations={str(r[0]):signed(r[1]) for r in rows}
    for r in bounded_query("SELECT JSON_OBJECT('id',ID,'duration',Duration) FROM acore_world.spellduration_dbc LIMIT 10001;"):durations[str(r['id'])]=r['duration']
    rows,_=read_dbc('SpellRadius');radii={str(r[0]):struct.unpack('<f',struct.pack('<I',r[1]))[0] for r in rows}
    for row in bounded_query("SELECT JSON_OBJECT('id',ID,'radius',Radius) FROM acore_world.spellradius_dbc LIMIT 10001;"):radii[str(row['id'])]=row['radius']
    rows,_=read_dbc('SpellRange');ranges={str(r[0]):[struct.unpack('<f',struct.pack('<I',v))[0] for v in r[3:5]] for r in rows}
    for row in bounded_query("SELECT JSON_OBJECT('id',ID,'range',JSON_ARRAY(RangeMax_1,RangeMax_2)) FROM acore_world.spellrange_dbc LIMIT 10001;"):ranges[str(row['id'])]=row['range']
    wanted={r['id'] for group in metadata['recipes'].values() for r in group.values()}
    # Include all server item spells, rather than only profession outputs.
    selections=['SELECT spellid_'+str(i)+' AS id FROM acore_world.item_template WHERE spellid_'+str(i)+'>0' for i in range(1,6)]
    selections.append('SELECT requiredspell AS id FROM acore_world.item_template WHERE requiredspell>0')
    item_spells=query("SELECT JSON_OBJECT('id',id) FROM ("+' UNION '.join(selections)+') AS ids LIMIT 60001;')
    if len(item_spells)>=60001:raise ValueError('Item spell catalogue limit exceeded')
    wanted.update(r['id'] for r in item_spells)
    rows,text=read_dbc('ItemSet');sets={str(r[0]):{'name':text(r[1]),'spells':list(r[35:43]),'counts':list(r[43:51])} for r in rows}
    set_fields=["'id',ID","'name',Name_Lang_enUS","'spells',JSON_ARRAY("+','.join('SetSpellID_'+str(i) for i in range(1,9))+')',"'counts',JSON_ARRAY("+','.join('SetThreshold_'+str(i) for i in range(1,9))+')']
    for row in bounded_query('SELECT JSON_OBJECT('+','.join(set_fields)+') FROM acore_world.itemset_dbc LIMIT 10001;'):sets[str(row.pop('id'))]=row
    wanted.update(s for v in sets.values() for s in v['spells'] if s>0)
    rows,text=read_dbc('SpellItemEnchantment');enchants={str(r[0]):text(r[14]) for r in rows}
    for row in bounded_query("SELECT JSON_OBJECT('id',ID,'text',Name_Lang_enUS) FROM acore_world.spellitemenchantment_dbc LIMIT 10001;"):enchants[str(row['id'])]=row['text']
    rows,_=read_dbc('GemProperties');gems={str(r[0]):r[1] for r in rows}
    for row in bounded_query("SELECT JSON_OBJECT('id',ID,'enchant',Enchant_Id) FROM acore_world.gemproperties_dbc LIMIT 10001;"):gems[str(row['id'])]=row['enchant']
    rows,text=read_dbc('Faction');factions={str(r[0]):text(r[23]) for r in rows}
    for row in bounded_query("SELECT JSON_OBJECT('id',ID,'name',Name_Lang_enUS) FROM acore_world.faction_dbc LIMIT 10001;"):factions[str(row['id'])]=row['name']
    # Class trainer offers are also used by the independent What's Training page.
    offers=bounded_query("SELECT DISTINCT JSON_OBJECT('class',t.Requirement,'spell',s.SpellId,'level',s.ReqLevel,'cost',s.MoneyCost,'skill',s.ReqSkillLine,'skill_rank',s.ReqSkillRank,'abilities',JSON_ARRAY(s.ReqAbility1,s.ReqAbility2,s.ReqAbility3)) FROM acore_world.trainer t JOIN acore_world.trainer_spell s ON s.TrainerId=t.Id WHERE t.Type=0 AND t.Requirement IN (1,2,3,4,5,6,7,8,9,11) LIMIT 20001;",20001)
    wanted.update(r['spell'] for r in offers)
    wanted.update(s for r in offers for s in r['abilities'] if s>0)
    rows,_=read_dbc('Talent');talents=sorted({s for r in rows for s in r[4:9] if s>0})
    ranks=bounded_query("SELECT JSON_OBJECT('id',spell_id,'first',first_spell_id,'rank',`rank`) FROM acore_world.spell_ranks LIMIT 40001;",40001)
    requirements=bounded_query("SELECT JSON_OBJECT('id',spell_id,'required',req_spell) FROM acore_world.spell_required LIMIT 10001;")
    wanted.update(r['required'] for r in requirements)
    rows,_=read_dbc('SkillLineAbility');ability_rows={r[0]:{'id':r[0],'skill':r[1],'spell':r[2],'race':r[3],'class':r[4]} for r in rows}
    for row in bounded_query("SELECT JSON_OBJECT('id',ID,'skill',SkillLine,'spell',Spell,'race',RaceMask,'class',ClassMask) FROM acore_world.skilllineability_dbc LIMIT 10001;"):ability_rows[row['id']]=row
    rows,_=read_dbc('SkillRaceClassInfo');skill_rows={r[0]:{'id':r[0],'skill':r[1],'race':r[2],'class':r[3]} for r in rows}
    for row in bounded_query("SELECT JSON_OBJECT('id',ID,'skill',SkillID,'race',RaceMask,'class',ClassMask) FROM acore_world.skillraceclassinfo_dbc LIMIT 10001;"):skill_rows[row['id']]=row
    checked=set();selected={}
    fields=["'id',ID","'name',Name_Lang_enUS","'description',Description_Lang_enUS","'cast',CastingTimeIndex","'duration',DurationIndex","'proc_chance',ProcChance","'stacks',CumulativeAura","'range',RangeIndex","'rank',NameSubtext_Lang_enUS","'icon_id',SpellIconID","'attributes',Attributes","'power_type',PowerType","'cost',ManaCost","'cost_per_level',ManaCostPerLevel","'cost_percent',ManaCostPct","'recovery',RecoveryTime","'category_recovery',CategoryRecoveryTime"]
    for key,column in [('effects','Effect'),('base','EffectBasePoints'),('die','EffectDieSides'),('period','EffectAuraPeriod'),('per_level','EffectRealPointsPerLevel'),('misc','EffectMiscValue'),('triggers','EffectTriggerSpell'),('chain','EffectChainTargets'),('radius','EffectRadiusIndex')]:
        fields.append("'"+key+"',JSON_ARRAY("+','.join(column+'_'+str(i) for i in range(1,4))+')')
    while wanted-checked:
        batch=sorted(wanted-checked)[:500];checked.update(batch)
        if len(checked)>60000:raise ValueError('Tooltip spell dependency limit exceeded')
        for r in query('SELECT JSON_OBJECT('+','.join(fields)+') FROM acore_world.spell_dbc WHERE ID IN ('+','.join(map(str,batch))+');'):spells[r['id']]=r
        for sid in batch:
            spell=spells.get(sid)
            if not spell:continue
            spell['icon']=icons.get(spell.get('icon_id'))
            selected[str(sid)]=spell
            wanted.update(int(ref) for pair in re.findall(r'\$(\d+)[a-zA-Z]|\$@spell(?:name|desc)(\d+)',spell['description'] or '') for ref in pair if ref)
            wanted.update(i for i in spell['triggers'] if i>0)
            for effect,value in zip(spell['effects'],spell['misc']):
                glyph=glyphs.get(str(value)) if effect==74 else None
                if glyph:wanted.add(glyph['spell'])
    result={'format':1,'spells':selected,'casts':casts,'durations':durations,'glyphs':glyphs,'sets':sets,'enchants':enchants,'factions':factions,'gems':gems,'radii':radii,'ranges':ranges}
    result['training']={'offers':offers,'ranks':ranks,'requirements':requirements,'talents':talents,
                        'abilities':[r for r in ability_rows.values() if str(r['spell']) in selected],
                        'skill_rules':list(skill_rows.values())}
    output=Path(output);output.parent.mkdir(exist_ok=True,parents=True);tmp=output.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False));tmp.replace(output)
    print('Prepared tooltip text for',len(selected),'spells.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profession-metadata',default=str(ROOT/'assets/profession-metadata.json'))
    parser.add_argument('--output',default=str(ROOT/'assets/tooltip-metadata.json'))
    args=parser.parse_args();prepare(args.profession_metadata,args.output)
