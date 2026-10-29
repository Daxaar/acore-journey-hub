"""Explainable role-weighted saved gear comparison; never performs game mutations."""
from collections import defaultdict
from datetime import datetime,timezone
import copy
import json
from pathlib import Path
import threading
import time
from armory import EQUIPMENT,read_inventory_sql,ITEM_TOOLTIP_FIELDS
from gear_sources import ROOT,read_snapshot,read_sources,read_items,load_json
from mysql_access import DatabaseError
from professions import applicable
from gear_eligibility import QuestEligibility,read_eligibility,npc_faction_access
from quest_log import CLASSES

ROLES={'tank':'Tank','healer':'Healer','melee':'Melee DPS','ranged':'Ranged physical DPS','caster':'Caster DPS'}
STATS={0:'mana',1:'health',3:'agility',4:'strength',5:'intellect',6:'spirit',7:'stamina',12:'defense',13:'dodge',14:'parry',15:'block_rating',
 16:'melee_hit',17:'ranged_hit',18:'spell_hit',19:'melee_crit',20:'ranged_crit',21:'spell_crit',28:'melee_haste',29:'ranged_haste',30:'spell_haste',
 31:'hit',32:'crit',35:'resilience',36:'haste',37:'expertise',38:'attack_power',39:'ranged_power',41:'healing',42:'spell_power',43:'mp5',44:'armor_penetration',45:'spell_power',48:'block_value'}
WEIGHTS={
 'tank':{'stamina':1,'strength':.35,'agility':.45,'armor':.035,'defense':1,'dodge':.9,'parry':.8,'block_rating':.7,'block_value':.4,'weapon_dps':1,'hit':.4,'expertise':.5,'health':.08},
 'healer':{'intellect':1,'spirit':.8,'spell_power':1.5,'healing':.7,'mp5':2,'stamina':.2,'crit':.5,'haste':.6,'mana':.02},
 'melee':{'strength':1,'agility':.8,'attack_power':.5,'weapon_dps':5,'hit':1,'crit':.9,'expertise':.9,'haste':.7,'stamina':.25,'armor_penetration':.5},
 'ranged':{'agility':1.2,'ranged_power':.5,'attack_power':.5,'ranged_dps':5,'intellect':.2,'stamina':.25,'hit':1,'crit':.9,'haste':.7},
 'caster':{'spell_power':1.5,'intellect':1,'spirit':.5,'hit':.9,'crit':.7,'haste':.7,'stamina':.25,'mana':.02}}
WEAPON_SKILLS={0:44,1:172,2:45,3:46,4:54,5:160,6:229,7:43,8:55,10:136,13:473,15:173,16:176,18:226,19:228,20:356}
ARMOR_SKILLS={1:415,2:414,3:413,4:293,6:433}
SLOTS={1:[0],2:[1],3:[2],5:[4],6:[5],7:[6],8:[7],9:[8],10:[9],11:[10,11],12:[12,13],13:[15,16],14:[16],15:[17],16:[14],17:[15],20:[4],21:[15],22:[16],23:[16],25:[17],26:[17],28:[17]}
OWNED={'owned','guild'}


class PlannerPreferences:
    def __init__(self,path=None):
        self.path=path;self.lock=threading.Lock();self.roles={}
        if path and path.exists():
            data=json.loads(path.read_text());self.roles=data.get('roles',{})
            if not isinstance(self.roles,dict) or any(not str(k).isdigit() or v not in ROLES for k,v in self.roles.items()):raise ValueError('Invalid planner preferences.')
    def get(self):
        with self.lock:return dict(self.roles)
    def save(self,guid,role):
        if type(guid)is not int or not 1<=guid<=4294967295 or role not in (*ROLES,''):raise ValueError('Choose a character and supported combat role.')
        with self.lock:
            roles=dict(self.roles)
            if role:roles[str(guid)]=role
            else:roles.pop(str(guid),None)
            if self.path:
                tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps({'roles':roles})+'\n');tmp.chmod(0o600);tmp.replace(self.path)
            self.roles=roles;return dict(roles)


def mask_allows(mask,value):return mask is None or mask<=0 or mask&(1<<(value-1))!=0


def weights(role,cls):
    result=dict(WEIGHTS.get(role,{}))
    if role=='melee' and cls==4:result.update(strength=.5,agility=1.1)
    if role=='melee' and cls in (1,2,6):result['strength']=1.2
    # Match attack-specific ratings to the selected intended role.
    kind='spell' if role in ('healer','caster') else 'ranged' if role=='ranged' else 'melee'
    for stat in ('hit','crit','haste'):result[kind+'_'+stat]=result.get(stat,0)
    if cls==11:result['weapon_dps']=0
    return result


def spell_stats(spell):
    stats=defaultdict(float);unknown=False
    if not spell:return stats,True
    for i,effect in enumerate(spell['effects']):
        if not effect:continue
        aura=spell['auras'][i];misc=spell['misc'][i];amount=spell['base'][i]+(1 if spell['die'][i] else 0)
        if effect!=6 or spell['die'][i]>1 or spell['scale'][i]:unknown=True;continue
        if aura==29:
            keys={0:['strength'],1:['agility'],2:['stamina'],3:['intellect'],4:['spirit']}.get(misc,['strength','agility','stamina','intellect','spirit'] if misc==-1 else [])
        else:keys={34:['health'],35:['mana'] if misc==0 else [],99:['attack_power'],124:['ranged_power'],135:['healing'],85:['mp5'] if misc==0 else [],22:['armor'] if misc==1 else [],13:['spell_power'] if misc==126 else []}.get(aura,[])
        if not keys:unknown=True
        for key in keys:stats[key]+=amount
    return stats,unknown


def effective(item,instance,metadata):
    stats=defaultdict(float);notes=[]
    for i in range(1,11):
        value=item.get('stat_value'+str(i)) or 0;kind=item.get('stat_type'+str(i))
        if value and kind in STATS:stats[STATS[kind]]+=value
        elif value:notes.append('Unscored stat #'+str(kind))
    stats['armor']+=item.get('armor',0);stats['block_value']+=item.get('block',0)
    if item.get('class')==2 and item.get('delay',0)>0:
        damage=sum((item.get('dmg_min'+str(i),0)+item.get('dmg_max'+str(i),0))/2 for i in (1,2))*1000/item['delay']
        stats['ranged_dps' if item['InventoryType'] in (15,25,26) else 'weapon_dps']+=damage
    for i in range(1,6):
        sid=item.get('spellid_'+str(i)) or 0
        if sid>0:
            if item.get('spelltrigger_'+str(i))!=1:notes.append('Proc/use effect #'+str(sid)+' is not simulated');continue
            added,unknown=spell_stats(metadata.get('spells',{}).get(str(sid)));notes.extend(['Unresolved passive effect #'+str(sid)] if unknown else [])
            for key,value in added.items():stats[key]+=value
    enchants=[]
    if instance:
        parts=str(instance.get('enchants') or '').split()
        enchants=[int(x) for x in parts[::3] if x.isdigit() and int(x)]
        if instance.get('random',0)>0 and not any(int(x) for x in parts[21::3] if x.isdigit()):enchants+=metadata.get('properties',{}).get(str(instance['random']),[])
        if instance.get('random',0)<0:notes.append('Random-suffix scaling is not resolved')
    elif item.get('RandomProperty') or item.get('RandomSuffix'):notes.append('Random roll varies; base stats only')
    for eid in enchants:
        enchant=metadata.get('enchants',{}).get(str(eid))
        if not enchant:notes.append('Unresolved enchantment #'+str(eid));continue
        if enchant.get('condition'):notes.append('Conditional gem/enchantment #'+str(eid)+' requires review');continue
        for kind,amount,arg in zip(enchant['types'],enchant['amount'],enchant['args']):
            if not kind:continue
            if kind==5 and arg in STATS:stats[STATS[arg]]+=amount
            elif kind==4 and arg==0:stats['armor']+=amount
            elif kind==3:
                added,unknown=spell_stats(metadata.get('spells',{}).get(str(arg)))
                for key,value in added.items():stats[key]+=value
                if unknown:notes.append('Unresolved enchantment effect #'+str(eid))
            else:notes.append('Unscored enchantment effect #'+str(eid))
    if item.get('ScalingStatDistribution') or item.get('ScalingStatValue'):notes.append('Scaling item stats require review')
    if item.get('itemset'):notes.append('Set bonuses are not simulated')
    return dict(stats),list(dict.fromkeys(notes))


def equip_checks(item,char):
    if not (item.get('AllowableClass',-1)&(1<<(char['class']-1))) or not (item.get('AllowableRace',-1)&(1<<(char['race']-1))):return None
    alliance=char['race'] in (1,3,4,7,11);extra=item.get('FlagsExtra',0)
    if extra&1 and alliance or extra&2 and not alliance:return None
    if item['class']==2 and item['subclass']==20:return None
    slot=item.get('InventoryType');skills=char['skills'];notes=[];level=item.get('RequiredLevel',0)
    if slot not in SLOTS:return None
    if item['class']==2 and not skills.get(WEAPON_SKILLS.get(item['subclass'],-1),0):return None
    if item['class']==4:
        skill=ARMOR_SKILLS.get(item['subclass'])
        if skill and not skills.get(skill,0):return None
        if item['subclass'] in (7,8,9,10) and char['class']!={7:2,8:11,9:7,10:6}[item['subclass']]:return None
        if slot==28 and item['subclass'] not in (7,8,9,10):return None
    if item.get('RequiredSkill') and skills.get(item['RequiredSkill'],0)<item.get('RequiredSkillRank',0):notes.append('Requires skill #'+str(item['RequiredSkill'])+' at '+str(item['RequiredSkillRank']))
    if item.get('requiredspell') and item['requiredspell'] not in char['spells']:notes.append('Requires spell #'+str(item['requiredspell']))
    if item.get('RequiredReputationFaction'):notes.append('Requires reputation rank '+str(item.get('RequiredReputationRank'))+' with faction #'+str(item['RequiredReputationFaction']))
    if item.get('requiredhonorrank') or item.get('RequiredCityRank'):notes.append('Honor/city rank restriction needs verification')
    if item.get('ItemLimitCategory'):notes.append('Unique-equipped category needs verification')
    return {'level':level,'notes':notes}


def transferable(instance,item,char):
    if instance.get('owner')==char['guid']:return True
    # Never treat the raid-trade flag as general permission to transfer a soulbound item.
    if item.get('Flags',0)&0x08000000:return instance.get('account')==char['account']
    if instance.get('flags',0)&1 or item.get('bonding') in (1,4,5):return False
    return True


def source_state(source,char,item,metadata=None):
    notes=[];availability='now';required=max(item.get('RequiredLevel',0),source.get('min_level',0))
    if required>char['level']:availability='soon' if required<=char['level']+2 else 'later';notes.append('Requires level '+str(required))
    kind=source['kind']
    if kind=='quest':
        q=source['quest'];qid=q['ID'];status=char['quests'].get(qid);repeat=q['SpecialFlags']&17 or q['Flags']&(4096|32768)
        if qid in char['rewarded'] and not repeat:return None
        if char.get('quest_eligibility') and char['quest_eligibility'](qid) is not True:return None
        for mask,value in [(q['AllowableRaces'],char['race']),(q['AllowableClasses'],char['class'])]:
            if not mask_allows(mask,value):return None
        if q['MaxLevel'] and char['level']>q['MaxLevel']:return None
        prev=q['PrevQuestID']
        if not status and prev and not (prev>0 and prev in char['rewarded'] or prev<0 and (abs(prev) in char['quests'] or abs(prev) in char['rewarded'])):
            availability='check';notes.append('Complete prerequisite quest #'+str(abs(prev)))
        if q['RequiredSkillID'] and char['skills'].get(q['RequiredSkillID'],0)<q['RequiredSkillPoints']:availability='check';notes.append('Quest profession requirement is not met')
        if not status:
            # Without all game conditions, never promise an unaccepted quest can be picked up.
            availability='check' if availability=='now' else availability
            notes.append('Quest giver availability and other scripted conditions still need checking')
        if q['ExclusiveGroup'] or q['conditions'] or repeat:availability='check';notes.append('Alternative, repeatable or conditional quest availability needs checking')
        if any(q.get(key) for key in ['RequiredMinRepFaction','RequiredMaxRepFaction','RequiredFactionId1','RequiredFactionId2']):availability='check';notes.append('Quest reputation requirements need checking')
        if q['QuestLevel']>char['level']+5:
            availability='later';notes.append('Quest suggested level '+str(q['QuestLevel'])+' is well above this character')
        if status==1:notes.append('Saved quest is ready to hand in')
        elif status:notes.append('Already in this character’s saved quest log')
    elif kind=='vendor':
        if npc_faction_access(metadata or {},char['race'],source.get('faction')) is not True:return None
        availability='check';notes.append('Faction access checked; confirm reputation, travel and stock; price is before discounts')
        if source['extended']:notes.append('Requires additional currencies/tokens (cost #'+str(source['extended'])+')')
        if source['cost']>char['money']:notes.append('Not enough saved money')
    elif kind=='craft':
        crafter=source['crafter']
        if item.get('bonding') in (1,4,5) and crafter['guid']!=char['guid']:return None
        if not source['learned']:availability='check';notes.append('Recipe is not learned; acquisition needs checking')
        if not source['materials_ready']:availability='check';notes.append('Crafting materials still needed')
        if crafter['skills'].get(source['skill'],0)<source['required_skill']:availability='check';notes.append('Crafter skill is too low')
        if source['focus'] or source['tools']:availability='check';notes.append('Verify workstation, tools and cooldown before crafting')
        notes.append('Materials checked in crafter’s carried bags; shared materials are not reserved')
    elif kind=='guild':availability='check';notes.append('Confirm guild withdrawal permission; bank contents are saved data')
    elif kind=='owned' and source['owner']!=char['guid']:
        notes.append('Transfer from '+source['owner_name']+'; saved binding flags allow transfer')
        if source.get('location')=='equipped':availability='check';notes.append('Donor must unequip this item; their own loadout would lose it')
        alliance={1,3,4,7,11}
        if source.get('owner_race') and (source['owner_race'] in alliance)!=(char['race'] in alliance):
            return None
    if required>char['level'] and availability=='check':
        availability='soon' if required<=char['level']+2 else 'later'
        notes.append('Additional acquisition requirements still need checking')
    return availability,required,notes


def effort_points(source,char):
    kind=source['kind']
    if kind=='owned':return 1 if source.get('owner')==char['guid'] else 2
    if kind=='guild':return 2
    if kind=='quest':
        status=char['quests'].get(source['id'])
        return 1 if status==1 else 3 if status else 6
    if kind=='craft':return 2 if source['learned'] and source['materials_ready'] else 5 if source['learned'] else 8
    return 3+(5 if source.get('cost',0)>char['money'] else 0)+(5 if source.get('extended') else 0)


def compare_candidate(item,instance,char,source,metadata,threshold):
    role=char['role'];checks=equip_checks(item,char)
    if not role or checks is None:return None
    state=source_state(source,char,item,metadata)
    if state is None:return None
    availability,required,source_notes=state
    if required>char['level']+5:return None
    if source['kind'] in OWNED and not transferable(instance or {},item,char):return None
    if source['kind']=='guild' and source['guild'] not in char['guilds']:
        availability='check';source_notes.append('A group guild member must withdraw and transfer the item')
    stats,notes=effective(item,instance,metadata);notes+=checks['notes'];
    if char['class']==11 and item['class']==2 and role in ('tank','melee'):notes.append('Feral weapon attack-power conversions require review')
    w=weights(role,char['class'])
    equipped=char['equipped'];choices=[]
    for target in SLOTS[item['InventoryType']]:
        current=equipped.get(target);replace=[target]
        if current and instance and current['instance']['guid']==instance.get('guid'):continue
        if target==16:
            main=equipped.get(15)
            if main and main['template']['InventoryType']==17:continue
            if item['class']==2 and 674 not in char['spells'] and 49152 not in char['spells']:continue
        if item['InventoryType']==17:replace=[15,16]
        elif target==15 and equipped.get(15) and equipped[15]['template']['InventoryType']==17:replace=[15,16]
        if instance and any(slot not in replace and value['instance']['guid']==instance.get('guid') for slot,value in equipped.items()):continue
        duplicate=False
        for slot,value in equipped.items():
            if slot not in replace and value['template']['entry']==item['entry'] and (item.get('maxcount')==1 or item.get('Flags',0)&0x80000):duplicate=True
        if duplicate:continue
        previous=defaultdict(float);base_notes=[];old=[]
        for slot in replace:
            value=equipped.get(slot)
            if value:
                for key,n in value['stats'].items():previous[key]+=n
                base_notes+=value['notes'];old.append(value['template']['name'])
        delta={key:round(stats.get(key,0)-previous.get(key,0),3) for key in set(stats)|set(previous) if abs(stats.get(key,0)-previous.get(key,0))>.0001}
        base_score=sum(value*w.get(key,0) for key,value in previous.items());gain=sum(value*w.get(key,0) for key,value in delta.items())
        if gain<(0.01 if threshold==0 else max(1,abs(base_score)*threshold/100)):continue
        new_score=sum(value*w.get(key,0) for key,value in stats.items())
        note_list=list(dict.fromkeys(notes+base_notes+source_notes))
        review=bool(notes or base_notes)
        if checks['notes'] and availability=='now':availability='check'
        # Large source limits remain explicit. No unsupported effect is called a verified upgrade.
        choices.append({'item':item_brief(item,stats,notes),'slot':target,'slot_name':EQUIPMENT[target],
            'replaces':old or ['Empty slot'],'replaced_items':[{'id':equipped[slot]['template']['entry'],'name':equipped[slot]['template']['name']} for slot in replace if slot in equipped],'replace_slots':replace,'score':round(new_score,2),'baseline_score':round(base_score,2),
            'gain':round(gain,2),'gain_percent':round(gain/base_score*100,1) if base_score>0 else None,
            'delta':delta,'contributions':{key:round(value*w.get(key,0),2) for key,value in delta.items() if w.get(key,0)},
            'availability':availability,'required_level':required,'confidence':'review' if review else 'scored',
            'notes':note_list,'source':{key:value for key,value in source.items() if key not in ('quest','crafter')}|{'effort_points':effort_points(source,char),'eligibility':{'faction':'Alliance' if char['race'] in (1,3,4,7,11) else 'Horde','class':CLASSES.get(char['class'],'Unknown')} if source['kind']=='quest' else None},
            'resource':str(instance['guid']) if instance else None})
    return max(choices,key=lambda c:c['gain']) if choices else None


def item_brief(item,stats,notes):
    return {'id':item['entry'],'name':item['name'],'quality':item['Quality'],'level':item['ItemLevel'],
            'required_level':item['RequiredLevel'],'type':item['InventoryType'],'icon':item.get('icon'),
            'class_mask':item.get('AllowableClass'),'race_mask':item.get('AllowableRace'),
            'required_skill':item.get('RequiredSkill'),'required_skill_rank':item.get('RequiredSkillRank'),
            'stats':stats,'notes':notes,**{field:item.get(field,0) for field in ITEM_TOOLTIP_FIELDS},
            'sell_price':item.get('SellPrice',0),'description':item.get('description',''),'skill_rank':item.get('RequiredSkillRank',0)}


def adventure_plans(characters):
    buckets=defaultdict(list)
    for char in characters:
        for rec in char.get('recommendations',[]):
            if rec['confidence']!='scored' or rec['availability'] not in ('now','check'):continue
            buckets[rec['source']['activity']].append((char,rec))
    result=[]
    for key,values in buckets.items():
        chosen={};resources=set()
        for char,rec in sorted(values,key=lambda pair:pair[1]['gain']/max(10,pair[1]['baseline_score']),reverse=True):
            if char['name'] in chosen or rec['resource'] and rec['resource'] in resources:continue
            chosen[char['name']]={'character':char['name'],'item':rec['item']['name'],'item_id':rec['item']['id'],'item_details':rec['item'],'gain':rec['gain'],'availability':rec['availability'],'relative_gain':rec['gain']/max(10,rec['baseline_score']),'effort':rec['source'].get('effort_points',6)}
            if rec['resource']:resources.add(rec['resource'])
        if not chosen:continue
        source=values[0][1]['source'];owned=source['kind'] in OWNED
        value=sum(row['relative_gain'] for row in chosen.values());effort=max(row['effort'] for row in chosen.values())
        result.append({'key':key,'title':source['activity_name'],'kind':source['kind'],'beneficiaries':list(chosen.values()),
            'value':round(value,2),'members':len(chosen),'effort':'Low' if effort<=2 else 'Moderate' if effort<=5 else 'High',
            'location':source.get('zone'),'priority':(1000 if owned else 0)+(len(chosen)*2+min(10,value))*10/effort,
            'notes':'One best reward per character; shared item instances counted once. Materials, quest availability and bank permissions still need checking.'})
    return sorted(result,key=lambda p:-p['priority'])[:20]


class GearPlanner:
    def __init__(self,root=ROOT,reader=read_inventory_sql,preferences=None):
        self.root=Path(root);self.reader=reader;self.preferences=preferences or PlannerPreferences()
        self.lock=threading.Lock();self.cached={};self.catalog={};self.eligibility_catalog=None
        self.metadata={};self.item_metadata={};self.professions={};self.quest_metadata={};self.metadata_loaded=False
    def set_role(self,group,guid,role):
        from gear_sources import query
        from mysql_access import name_filter
        if type(guid)is not int or guid<=0 or role not in (*ROLES,'') or not group:raise ValueError('Choose a member of the selected group and a role.')
        rows=query("SELECT JSON_OBJECT('guid',c.guid) FROM acore_characters.characters c WHERE "+name_filter('c',group['members'])+f' AND c.guid={guid};',self.reader)
        if not rows:raise ValueError('That character is not in the currently selected group.')
        roles=self.preferences.save(guid,role)
        with self.lock:self.cached.clear()
        return roles
    def get(self,group,known_names=(),threshold=5):
        if type(threshold)is not int or threshold not in (0,5,10,20):raise ValueError('Choose a supported minimum improvement.')
        if not group:return {'group':None,'characters':[],'activities':[],'roles':ROLES,'refreshed_at':datetime.now(timezone.utc).isoformat(),'warnings':[]}
        roles=self.preferences.get();key=(tuple(group['members']),group['id'],tuple(known_names),tuple(sorted(roles.items())),threshold)
        with self.lock:
            prior=self.cached.get(key)
            if prior and time.monotonic()-prior[0]<10:return copy.deepcopy(prior[1])
            if not self.metadata_loaded:
                self.metadata=load_json('gear-metadata.json',self.root);self.item_metadata=load_json('item-metadata.json',self.root)
                self.professions=load_json('profession-metadata.json',self.root);self.quest_metadata=load_json('quest-metadata.json',self.root);self.metadata_loaded=True
            rows=read_snapshot(group['members'],known_names,self.reader)
            chars=[];instances=[r for r in rows if r['kind'] in ('inventory','guild_item')]
            for name in group['members']:
                row=next((r for r in rows if r['kind']=='character' and r['name'].lower()==name.lower()),None)
                if not row:chars.append({'name':name,'found':False,'role':'','equipment':[],'recommendations':[]});continue
                char=dict(row);guid=char['guid'];char['found']=True;char['role']=roles.get(str(guid),'')
                char['skills']={r['id']:r['value'] for r in rows if r['kind']=='skill' and r['guid']==guid}
                char['spells']={r['id'] for r in rows if r['kind']=='spell' and r['guid']==guid}
                char['rewarded']={r['id'] for r in rows if r['kind']=='rewarded' and r['guid']==guid }
                char['quests']={r['id']:r['status'] for r in rows if r['kind']=='quest' and r['guid']==guid and r['status'] in (1,3,5)}
                char['guilds']={r['guild'] for r in rows if r['kind']=='guild_member' and r['guid']==guid}
                char['materials']={r['entry']:r['count'] for r in rows if r['kind']=='material' and r['guid']==guid}
                chars.append(char)
            active=[c for c in chars if c['found']];cap=min(85,max((c['level'] for c in active),default=1)+5)
            ready=any(c['role'] for c in active);world_quests=[];vendors=[];recipes=[]
            if ready:
                catalog=self.catalog.get(cap)
                if not catalog or time.monotonic()-catalog[0]>300:
                    world_quests,vendors=read_sources(cap,self.reader);self.catalog[cap]=(time.monotonic(),world_quests,vendors)
                    if len(self.catalog)>8:self.catalog.pop(next(iter(self.catalog)))
                else:_,world_quests,vendors=catalog
                craft_equipment={int(k) for k,v in self.professions.get('items',{}).items() if v.get('class') in (2,4)}
                for skill,records in self.professions.get('recipes',{}).items():
                    for rec in records.values():
                        if any(o['id'] in craft_equipment for o in rec.get('outputs',[])):recipes.append((int(skill),rec))
            ids={i['entry'] for i in instances}
            ids.update(i for q in world_quests for i in q['rewards'] if i)
            ids.update(v['entry'] for v in vendors)
            ids.update(o['id'] for _,rec in recipes for o in rec['outputs'])
            items=read_items(ids,self.reader)
            for item in items.values():item['icon']=self.item_metadata.get('icons',{}).get(str(item['displayid']))
            warnings=[]
            if not self.metadata:warnings.append('Effect metadata unavailable: affected items are marked for review rather than treated as guaranteed upgrades.')
            if not self.professions:warnings.append('Profession catalogue unavailable; crafting opportunities are not included.')
            for char in active:
                char['equipped']={}
                for instance in instances:
                    if instance['kind']=='inventory' and instance['owner']==char['guid'] and instance['bag']==0 and instance['slot']<19 and instance['entry'] in items:
                        item=items[instance['entry']];stats,notes=effective(item,instance,self.metadata)
                        char['equipped'][instance['slot']]={'template':item,'instance':instance,'stats':stats,'notes':notes}
            if ready:
                if not self.eligibility_catalog or time.monotonic()-self.eligibility_catalog[0]>300:
                    records,conditions=read_eligibility(self.reader)
                    self.eligibility_catalog=(time.monotonic(),QuestEligibility(records,self.metadata,conditions))
                eligibility=self.eligibility_catalog[1]
                for char in active:char['quest_eligibility']=eligibility.for_character(char)
                if not self.metadata.get('faction_templates') or not self.metadata.get('player_factions'):warnings.append('Faction data unavailable: quests and vendors with unverified faction eligibility are omitted.')
            sources=defaultdict(list)
            for inst in instances:
                if inst['entry'] not in items:continue
                if inst['kind']=='guild_item':
                    source={'kind':'guild','label':inst['guild_name']+' · tab '+str(inst['tab']+1)+', slot '+str(inst['slot']+1),'guild':inst['guild'],
                        'activity':'guild:'+str(inst['guild']),'activity_name':'Check '+inst['guild_name']+' guild bank'}
                else:source={'kind':'owned','label':inst['owner_name']+' · '+inst['location'],'owner':inst['owner'],'owner_name':inst['owner_name'],
                    'location':inst['location'],'owner_race':inst.get('owner_race'),
                    'activity':'owned:'+str(inst['owner']),'activity_name':'Use equipment owned by '+inst['owner_name']}
                sources[inst['entry']].append((source,inst))
            for q in world_quests:
                category=q['QuestSortID'];zone=self.quest_metadata.get('areas' if category>0 else 'sorts',{}).get(str(abs(category)),'Quest category #'+str(category))
                source={'kind':'quest','label':q['LogTitle']+' · Quest #'+str(q['ID']),'id':q['ID'],'min_level':max(q['MinLevel'],0),
                    'activity':'quest:'+str(q['ID']),'activity_name':q['LogTitle'],'zone':zone,'quest_level':q['QuestLevel'],'suggested_players':q['SuggestedGroupNum'],'quest':q,'url':'https://www.wowhead.com/wotlk/quest='+str(q['ID'])}
                for iid in set(q['rewards']):
                    if iid:sources[iid].append((source,None))
            for vendor in vendors:
                source={**vendor,'label':vendor['name']+' · '+str(vendor['cost'])+' copper / '+str(vendor['buy_count'])+' items',
                    'activity':'vendor:'+str(vendor['npc']),'activity_name':'Visit '+vendor['name'],'url':'https://www.wowhead.com/wotlk/npc='+str(vendor['npc'])}
                sources[vendor['entry']].append((source,None))
            for skill,rec in recipes:
                for crafter in active:
                    matches=[a for a in rec['abilities'] if applicable(a,crafter)]
                    if not matches or not crafter['skills'].get(skill):continue
                    ability=min(matches,key=lambda a:a['required']);value=crafter['skills'][skill]
                    if ability['required']>value+25:continue
                    learned=rec['id'] in crafter['spells'] or any(a.get('acquire')==2 or a.get('acquire')==1 and value>=a['required'] for a in matches)
                    required_materials=defaultdict(int)
                    for iid,amount in rec['reagents']:required_materials[iid]+=amount
                    source={'kind':'craft','label':rec['name']+' · crafter '+crafter['name'],'id':rec['id'],'crafter':crafter,
                        'skill':skill,'required_skill':ability['required'],'learned':learned,
                        'materials_ready':all(crafter['materials'].get(i,0)>=n for i,n in required_materials.items()),
                        'reagents':[{'id':i,'name':self.professions.get('items',{}).get(str(i),{}).get('name','Item #'+str(i)),'required':n,'owned':crafter['materials'].get(i,0)} for i,n in required_materials.items()],
                        'focus':bool(rec.get('focus')),'tools':bool(rec.get('tools') or rec.get('tool_categories')),
                        'activity':'craft:'+str(skill)+':'+str(crafter['guid']),'activity_name':'Craft upgrades with '+crafter['name'],
                        'url':'https://www.wowhead.com/wotlk/spell='+str(rec['id'])}
                    for out in rec['outputs']:sources[out['id']].append((source,None))
            for char in active:
                recommendations=[]
                if char['role']:
                    for iid,options in sources.items():
                        item=items.get(iid)
                        if not item or item.get('RequiredLevel',0)>char['level']+5:continue
                        for source,instance in options:
                            rec=compare_candidate(item,instance,char,source,self.metadata,threshold)
                            if rec:recommendations.append(rec)
                recommendations.sort(key=lambda r:(r['source']['kind'] not in OWNED,{'now':0,'check':1,'soon':2,'later':3}[r['availability']],r['confidence']!='scored',-r['gain']/max(10,r['baseline_score'])))
                # Keep useful alternatives per slot and source type rather than hundreds of duplicate vendors.
                seen=set();kept=[]
                for rec in recommendations:
                    identity=(rec['item']['id'],rec['slot'],rec['source']['kind'],rec['resource'])
                    if identity in seen:continue
                    seen.add(identity);kept.append(rec)
                char['recommendations']=kept[:120];char['recommendation_count']=len(kept)
            claims=defaultdict(set)
            for char in active:
                for rec in char['recommendations']:
                    if rec['resource']:claims[rec['resource']].add(char['name'])
            for char in active:
                for rec in char['recommendations']:rec['competes_with']=sorted(claims.get(rec['resource'],set())-{char['name']})
            activities=adventure_plans(active)
            public=[]
            for char in chars:
                if not char['found']:public.append(char);continue
                equipment=[]
                for slot,label in enumerate(EQUIPMENT):
                    value=char['equipped'].get(slot)
                    equipment.append({'slot':slot,'label':label,'item':item_brief(value['template'],value['stats'],value['notes']) if value else None})
                public.append({k:char[k] for k in ('guid','name','class','race','level','role','found','recommendations','recommendation_count')}|{'equipment':equipment,'weights':weights(char['role'],char['class'])})
            result={'group':copy.deepcopy(group),'characters':public,'activities':activities,'roles':ROLES,'threshold':threshold,
                'refreshed_at':datetime.now(timezone.utc).isoformat(),'warnings':warnings,'owner_count':sum(r['kind']=='owner' for r in rows),
                'coverage':'Owned gear, quest rewards, crafting and vendors. Dungeon/world-drop acquisition and full combat simulation are later phases.',
                'scope':'Other characters on group accounts plus configured groups/watch list; group guild banks. Equipped donor items may displace their existing gear.'}
            if len(self.cached)>=8:self.cached.pop(next(iter(self.cached)))
            self.cached[key]=(time.monotonic(),result);return copy.deepcopy(result)
