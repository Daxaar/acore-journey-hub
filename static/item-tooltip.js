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
 function render(tooltip,item){
  const heading=el('div',undefined,'tooltip-heading');heading.append(icon(item),itemTitle(item));tooltip.replaceChildren(heading);
  tooltip.append(el('p','Item level '+(item.level??'unknown')));
  if(item.required_level)tooltip.append(el('p','Requires level '+item.required_level));
  if(item.required_skill&&item.skill_rank)tooltip.append(el('p','Requires profession skill '+item.skill_rank));
  if(item.description)tooltip.append(el('p',item.description,'tooltip-description'));
  const line=(text,cls)=>tooltip.append(el('p',text,cls));
  const binding={1:'Binds when picked up',2:'Binds when equipped',3:'Binds when used',4:'Quest item',5:'Quest item'};
  if(binding[item.bonding])line(binding[item.bonding]);
  if(item.armor)line(item.armor+' Armor');
  if(item.block)line(item.block+' Block');
  if(item.dmg_max1){line(item.dmg_min1+'–'+item.dmg_max1+' Damage');if(item.delay)line('Speed '+(item.delay/1000).toFixed(2)+' · '+((item.dmg_min1+item.dmg_max1)*500/item.delay).toFixed(1)+' damage per second');}
  for(let i=1;i<=10;i++)if(item['stat_value'+i])line((item['stat_value'+i]>0?'+':'')+item['stat_value'+i]+' '+(stats[item['stat_type'+i]]||'Stat #'+item['stat_type'+i]),'tooltip-stat');
  if(item.ContainerSlots)line(item.ContainerSlots+'-slot bag');
  if(item.MaxDurability)line('Maximum durability '+item.MaxDurability);
  const sell=el('p','Sell Price: ');sell.append(money(item.sell_price??0));tooltip.append(sell);
 }
 function position(tooltip,target,event){
  const rect=target.getBoundingClientRect(),box=tooltip.getBoundingClientRect();
  const x=event?event.clientX:rect.left,y=event?event.clientY:rect.top;
  tooltip.style.left=Math.max(8,Math.min(x+12,innerWidth-box.width-12))+'px';
  tooltip.style.top=Math.max(8,Math.min(y-box.height-12,innerHeight-box.height-12))+'px';
 }
 return {render,position};
})();
