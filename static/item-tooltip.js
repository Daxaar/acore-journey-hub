"use strict";
window.ItemTooltip = (() => {
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const stats={0:'Mana',1:'Health',3:'Agility',4:'Strength',5:'Intellect',6:'Spirit',7:'Stamina',12:'Defense rating',13:'Dodge rating',14:'Parry rating',15:'Block rating',16:'Melee hit rating',17:'Ranged hit rating',18:'Spell hit rating',19:'Melee critical strike rating',20:'Ranged critical strike rating',21:'Spell critical strike rating',31:'Hit rating',32:'Critical strike rating',35:'Resilience rating',36:'Haste rating',38:'Attack power',39:'Ranged attack power',43:'Mana per 5 sec',44:'Armor penetration rating',45:'Spell power',46:'Health per 5 sec',47:'Spell penetration',48:'Block value'};
 function money(value){
  const n=el('span',undefined,'money');
  if(value===null||value===undefined){n.textContent='Bid only';return n;}
  let copper=Math.ceil(Number(value));const gold=Math.floor(copper/10000),silver=Math.floor(copper%10000/100);copper%=100;
  n.setAttribute('aria-label',`${gold} gold, ${silver} silver, ${copper} copper`);
  for(const [amount,denomination,show] of [[gold,'gold',gold>0],[silver,'silver',silver>0||gold>0],[copper,'copper',copper>0||(!gold&&!silver)]]){
   if(show)n.append(document.createTextNode(amount.toLocaleString()),el('i',undefined,'coin '+denomination));
  }
  return n;
 }
 function itemTitle(item){return el('h3',item.name,'quality-'+item.quality);}
 function icon(item){const img=el('img',undefined,'item-icon');img.alt='';img.loading='lazy';img.src=item.icon?'/icons/'+encodeURIComponent(item.icon)+'.jpg':'/item-placeholder.svg';img.addEventListener('error',()=>{if(!img.src.endsWith('/item-placeholder.svg'))img.src='/item-placeholder.svg';});return img;}
 const slots={1:'Head',2:'Neck',3:'Shoulder',4:'Shirt',5:'Chest',6:'Waist',7:'Legs',8:'Feet',9:'Wrist',10:'Hands',11:'Finger',12:'Trinket',13:'One-Hand',14:'Shield',15:'Ranged',16:'Back',17:'Two-Hand',18:'Bag',19:'Tabard',20:'Chest',21:'Main Hand',22:'Off Hand',23:'Held In Off-hand',25:'Thrown',26:'Ranged',28:'Relic'};
 const armorTypes={1:'Cloth',2:'Leather',3:'Mail',4:'Plate',6:'Shield'};
 const weaponTypes={0:'Axe',1:'Axe',2:'Bow',3:'Gun',4:'Mace',5:'Mace',6:'Polearm',7:'Sword',8:'Sword',10:'Staff',13:'Fist Weapon',15:'Dagger',16:'Thrown',18:'Crossbow',19:'Wand',20:'Fishing Pole'};
 const cache=new Map(),requests=new WeakMap(),positions=new WeakMap();let requestId=0;
 function blend(detail,item){
  const result={...detail,...Object.fromEntries(Object.entries(item).filter(([,value])=>value!==undefined)),icon:item.icon||detail.icon};
  for(const key of ['spell_effects','effects_incomplete','class_names','race_names','glyph_type','max_stack','max_count','set_info','socket_bonus','faction_name','required_spell_name','skill_name','tooltip_complete'])if(detail[key]!==undefined)result[key]=detail[key];
  return result;
 }
 function renderContent(tooltip,item,recipe){
  tooltip.replaceChildren();
  const line=(text,cls)=>tooltip.append(el('p',text,cls));
  if(recipe){
   const heading=el('div',undefined,'tooltip-heading');heading.append(icon(item||recipe),el('h3',recipe.name));tooltip.append(heading);
   if(recipe.cast_time_ms!==null&&recipe.cast_time_ms!==undefined)line(recipe.cast_time_ms===0?'Instant':`${recipe.cast_time_ms/1000} sec cast`);
   line('Requires skill '+recipe.required_skill);
   const tools=[...(recipe.tools||[]).map(t=>t.name),...(recipe.tool_categories||[])];
   if(tools.length){line('Tools:');line([...new Set(tools)].join(', '),'tooltip-requirement');}
   if(recipe.focus)line('Requires '+recipe.focus);
   if(recipe.reagents?.length){line('Reagents:');line(recipe.reagents.map(r=>r.name+(r.required>1?' ('+r.required+')':'')).join(', '),'tooltip-requirement');}
   if(!item){if(recipe.tooltip_description||recipe.description)line(recipe.tooltip_description||recipe.description,'tooltip-stat');return;}
   const heading2=itemTitle(item);heading2.classList.add('tooltip-output-heading');tooltip.append(heading2);
  }else{const heading=el('div',undefined,'tooltip-heading');heading.append(icon(item),itemTitle(item));tooltip.append(heading);}
  line('Item Level '+(item.level??'unknown'),'tooltip-item-level');
  const binding={1:'Binds when picked up',2:'Binds when equipped',3:'Binds when used',4:'Quest item',5:'Quest item'};
  if(binding[item.bonding])line(binding[item.bonding]);
  if(item.max_count===1)line('Unique');
  if(item.glyph_type)line(item.glyph_type,'tooltip-requirement');
  const type=item.category===2?weaponTypes[item.subclass]:item.category===4?armorTypes[item.subclass]:null;
  if(slots[item.slot]||type)line([slots[item.slot],type].filter(Boolean).join(' · '));
  if(item.armor)line(item.armor+' Armor');if(item.block)line(item.block+' Block');
  if(item.dmg_max1){line(item.dmg_min1+'–'+item.dmg_max1+' Damage');if(item.delay)line('Speed '+(item.delay/1000).toFixed(2)+' · '+((item.dmg_min1+item.dmg_max1)*500/item.delay).toFixed(1)+' damage per second');}
  for(let i=1;i<=10;i++)if(item['stat_value'+i])line((item['stat_value'+i]>0?'+':'')+item['stat_value'+i]+' '+(stats[item['stat_type'+i]]||'Stat #'+item['stat_type'+i]),'tooltip-stat');
  for(const type of ['holy','fire','nature','frost','shadow','arcane'])if(item[type+'_res'])line('+'+item[type+'_res']+' '+type[0].toUpperCase()+type.slice(1)+' Resistance');
  for(const text of item.enchant_labels||[])line(text,'tooltip-stat');
  if(item.randomPropertyId)line('Saved random enchantments; scaled totals are not simulated.','tooltip-note');
  for(let i=1;i<=3;i++)if(item['socketColor_'+i])line(({1:'Meta',2:'Red',4:'Yellow',8:'Blue',14:'Prismatic'}[item['socketColor_'+i]]||'Unknown')+' Socket','tooltip-requirement');
  if(item.socket_bonus)line('Socket Bonus: '+item.socket_bonus,'tooltip-note');
  if(item.ContainerSlots)line(item.ContainerSlots+'-slot bag');
  if(item.MaxDurability)line(item.durability!==undefined?`Durability ${item.durability} / ${item.MaxDurability}`:'Durability '+item.MaxDurability+' / '+item.MaxDurability);
  if(item.class_names?.length)line('Classes: '+item.class_names.join(', '),'tooltip-requirement');
  if(item.race_names?.length)line('Races: '+item.race_names.join(', '),'tooltip-requirement');
  if(item.required_level)line('Requires Level '+item.required_level);
  if(item.required_skill&&item.skill_rank)line('Requires '+(item.skill_name||'profession skill')+' ('+item.skill_rank+')');
  if(item.required_spell_name)line('Requires '+item.required_spell_name);
  if(item.faction_name)line('Requires '+item.faction_name+' - '+(['Hated','Hostile','Unfriendly','Neutral','Friendly','Honored','Revered','Exalted'][item.required_rank]||'Reputation rank '+item.required_rank));
  if(item.description)line(item.description,'tooltip-description');
  for(const effect of item.spell_effects||[]){line((effect.label?effect.label+': ':'')+effect.text,'tooltip-stat');if(effect.cooldown_ms)line('Cooldown: '+(effect.cooldown_ms>=60000?effect.cooldown_ms/60000+' min':effect.cooldown_ms/1000+' sec'),'tooltip-note');}
  if(item.effects_incomplete)line('Some effect formulas require the game client; values are not guessed.','tooltip-note');
  if(item.set_info){line(item.set_info.name,'tooltip-item-level');for(const bonus of item.set_info.bonuses)line('('+bonus.count+') Set: '+bonus.text,'tooltip-note');}
  if(item.max_stack>1)line('Max Stack: '+item.max_stack);
  if(item.count>1)line('Stack: '+item.count);
  const sell=el('p','Sell Price: ');sell.append(money(item.sell_price??0));tooltip.append(sell);
 }
 function layout(tooltip){
  if(tooltip.querySelector(':scope > .tooltip-body'))return;
  const image=tooltip.querySelector('.tooltip-heading img');
  tooltip.classList.toggle('has-detached-icon',Boolean(image));
  if(!image)return;
  image.remove();image.classList.add('tooltip-icon');
  const body=el('div',undefined,'tooltip-body');body.append(...tooltip.childNodes);
  tooltip.replaceChildren(body,image);
 }
 function render(tooltip,item,recipe=null){
  const token=++requestId;requests.set(tooltip,token);
  const id=Number(item?.id??item?.entry),cached=cache.get(id);
  const fresh=cached&&Date.now()-cached.time<60000;
  renderContent(tooltip,item&&fresh&&cached.value?blend(cached.value,item):item,recipe);layout(tooltip);
  if(!item||!Number.isSafeInteger(id)||id<1||id>4294967295||item.tooltip_complete)return;
  if(fresh&&cached.value)return;
  let entry=fresh?cached:null;
  if(!entry){
   entry={time:Date.now()};cache.set(id,entry);if(cache.size>256)cache.delete(cache.keys().next().value);
   const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
   entry.pending=fetch('/api/item-tooltip?id='+id,{cache:'no-store',signal:controller.signal}).then(r=>r.json()).then(data=>{if(!data.ok||!data.item)throw new Error('Unavailable');entry.value=data.item;return data.item;}).finally(()=>clearTimeout(timeout));
   entry.pending.catch(()=>{if(cache.get(id)===entry)cache.delete(id);});
  }
  entry.pending.then(detail=>{
   if(requests.get(tooltip)!==token||tooltip.hidden||!tooltip.isConnected)return;
   renderContent(tooltip,blend(detail,item),recipe);layout(tooltip);
   const p=positions.get(tooltip);if(p&&p.target.isConnected)position(tooltip,p.target,p.event);
   tooltip.dispatchEvent(new Event('item-tooltip-updated'));
  }).catch(()=>{if(requests.get(tooltip)===token&&!tooltip.hidden)(tooltip.querySelector(':scope > .tooltip-body')||tooltip).append(el('p','Additional server item details unavailable.','tooltip-note'));});
 }
 function position(tooltip,target,event){
  target.classList.add('tooltip-trigger');
  positions.set(tooltip,{target,event:event?{clientX:event.clientX,clientY:event.clientY}:null});
  const rect=target.getBoundingClientRect(),box=tooltip.getBoundingClientRect();
  const x=event?event.clientX:rect.left,y=event?event.clientY:rect.top;
  const image=tooltip.querySelector(':scope > .tooltip-icon'),gutter=image?image.getBoundingClientRect().width+6:0;
  tooltip.style.left=Math.max(8+gutter,Math.min(x+12,innerWidth-box.width-12))+'px';
  tooltip.style.top=Math.max(8,Math.min(y-box.height-12,innerHeight-box.height-12))+'px';
 }
 return {render,position,layout};
})();
