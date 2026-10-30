"""Resolve server spell text for item tooltips without evaluating client expressions."""
import re

CLASSES={1:'Warrior',2:'Paladin',3:'Hunter',4:'Rogue',5:'Priest',6:'Death Knight',7:'Shaman',8:'Mage',9:'Warlock',11:'Druid'}
RACES={1:'Human',2:'Orc',3:'Dwarf',4:'Night Elf',5:'Undead',6:'Tauren',7:'Gnome',8:'Troll',10:'Blood Elf',11:'Draenei'}


def restrictions(mask,names):
    full=sum(1<<(i-1) for i in names)
    return [name for i,name in names.items() if mask&(1<<(i-1))] if mask>0 and mask&full!=full else []


def spell_text(spell_id,data,seen=(),allow_partial=False):
    if spell_id in seen or len(seen)>=8:return '',False
    spell=data.get('spells',{}).get(str(spell_id))
    if not spell:return '',False
    text=(spell.get('description') or '').replace('$B','\n').replace('$b','\n');complete=True
    def include(match):
        nonlocal complete
        sid=int(match[2]);other=data.get('spells',{}).get(str(sid))
        if match[1]=='name':
            if other:return other.get('name','')
        else:
            result,ok=spell_text(sid,data,(*seen,spell_id),allow_partial=allow_partial);complete&=ok;return result
        complete=False;return ''
    text=re.sub(r'\$@spell(name|desc)(\d+)',include,text)
    def token(match):
        nonlocal complete
        ref=data.get('spells',{}).get(match[1] or str(spell_id));kind=match[2].lower();index=int(match[3] or '1')-1
        if not ref or not 0<=index<3:complete=False;return '?'
        base=ref.get('base',[0,0,0])[index];die=ref.get('die',[0,0,0])[index]
        minimum=base+(1 if die>0 else die if die<0 else 0);maximum=base+(die if die>0 else -1 if die<0 else 0)
        if kind in ('s','m'):
            if any(ref.get('per_level',[0,0,0])):complete=False
            value=(minimum if kind=='m' else minimum if minimum==maximum else f'{minimum}–{maximum}')
            if match[2]=='M':value=maximum
            return str(abs(value) if isinstance(value,(int,float)) else value)
        if kind=='x':return str(ref.get('chain',[0,0,0])[index])
        if kind=='a':
            radius=data.get('radii',{}).get(str(ref.get('radius',[0,0,0])[index]))
            if radius is not None:return f'{radius:g}'
        if kind=='r':
            ranges=data.get('ranges',{}).get(str(ref.get('range')))
            if ranges and ranges[0]==ranges[1]:return f'{ranges[0]:g}'
        if kind=='o':
            duration=data.get('durations',{}).get(str(ref.get('duration')))
            period=ref.get('period',[0,0,0])[index]
            if duration and duration>0 and period:
                ticks=duration//period
                if any(ref.get('per_level',[0,0,0])):complete=False
                return str(abs(minimum*ticks)) if minimum==maximum else f'{abs(minimum*ticks)}–{abs(maximum*ticks)}'
        if kind=='t':return f"{ref.get('period',[0,0,0])[index]/1000:g}"
        if kind=='d':
            duration=data.get('durations',{}).get(str(ref.get('duration')))
            if duration is not None:return 'until cancelled' if duration<0 else f'{duration/1000:g} sec'
        if kind=='h' and 0<=ref.get('proc_chance',0)<=100:return str(ref.get('proc_chance',0))
        if kind=='u':return str(ref.get('stacks',0))
        complete=False;return '?'
    text=re.sub(r'\$(\d+)?([sSmMtdhuxaro])([1-3])?',token,text)
    text=re.sub(r'\$l([^:;]*):([^;]*);',lambda m:m[2],text)
    # Spellbook views can retain readable context while naming unresolved values.
    if allow_partial and ('$' in text or (not complete and '?' in text)):
        complete=False
        for _ in range(8):
            new=re.sub(r'\$\{[^{}]*\}', '[depends on current stats]',text)
            if new==text:break
            text=new
        text=re.sub(r'\$(?:AP|ap)\b','your attack power',text)
        text=re.sub(r'\$(?:SP|sp)\b','your spell power',text)
        text=re.sub(r'\$(?:PL|pl)\b','your level',text)
        if '$?' not in text:
            text=re.sub(r'\$(?:[0-9]+)?[a-zA-Z@]+[0-9]*','[client-calculated value]',text)
        text=text.replace('?','[client-calculated value]') if '$' not in text else text
    # Conditional/formula/client-only syntax is never guessed or executed.
    if '$' in text or (not complete and '?' in text):return '',False
    text=re.sub(r'\|H[^|]*\|h([^|]*)\|h',r'\1',text)
    text=re.sub(r'\|c[0-9a-fA-F]{8}|\|r','',text)
    return text.strip(),complete


def enrich_item(item,data):
    result=dict(item)
    result['class_names']=restrictions(item.get('AllowableClass',-1),CLASSES)
    result['race_names']=restrictions(item.get('AllowableRace',-1),RACES)
    effects=[];incomplete=False
    for i in range(1,6):
        sid=item.get('spellid_'+str(i),0)
        if sid<=0:continue
        spell=data.get('spells',{}).get(str(sid))
        if not spell:incomplete=True;continue
        effect_start=len(effects)
        glyph=next((data.get('glyphs',{}).get(str(value)) for effect,value in zip(spell.get('effects',[]),spell.get('misc',[])) if effect==74),None)
        if glyph:
            if glyph['flags'] in (0,1):result['glyph_type']='Minor Glyph' if glyph['flags']==1 else 'Major Glyph'
            effects.append({'label':'Use','text':'Permanently teaches you this glyph.'})
            text,ok=spell_text(sid,data)
            if not text:text,ok=spell_text(glyph['spell'],data)
            if text:effects.append({'label':'','text':text})
        else:
            text,ok=spell_text(sid,data)
            if text:effects.append({'label':{0:'Use',1:'Equip',2:'Chance on hit',4:'Use',5:'Use',6:'Use'}.get(item.get('spelltrigger_'+str(i)),'Effect'),'text':text})
        for effect in effects[effect_start:]:
            if effect.get('label')=='Use':
                cooldown=max(item.get('spellcooldown_'+str(i),0),item.get('spellcategorycooldown_'+str(i),0))
                if cooldown>0:effect['cooldown_ms']=cooldown
        incomplete|=not ok
    gem=data.get('gems',{}).get(str(item.get('gem_properties')))
    if gem:
        text=data.get('enchants',{}).get(str(gem))
        if text:effects.append({'label':'','text':text})
    set_info=data.get('sets',{}).get(str(item.get('itemset')))
    if set_info:
        bonuses=[]
        for sid,count in zip(set_info['spells'],set_info['counts']):
            if sid>0:
                text,ok=spell_text(sid,data);incomplete|=not ok
                if text:bonuses.append({'count':count,'text':text})
        result['set_info']={'name':set_info['name'],'bonuses':bonuses}
    bonus=data.get('enchants',{}).get(str(item.get('socketBonus')))
    if bonus:result['socket_bonus']=bonus
    faction=item.get('required_faction')
    if faction:result['faction_name']=data.get('factions',{}).get(str(faction)) or 'Faction #'+str(faction)
    required_spell=item.get('required_spell')
    if required_spell:result['required_spell_name']=data.get('spells',{}).get(str(required_spell),{}).get('name','Spell #'+str(required_spell))
    result['spell_effects']=effects;result['effects_incomplete']=incomplete
    return result
