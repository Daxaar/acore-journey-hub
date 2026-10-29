"use strict";
(() => {
 const $=id=>document.getElementById(id);
 const classes={1:'Warrior',2:'Paladin',3:'Hunter',4:'Rogue',5:'Priest',6:'Death Knight',7:'Shaman',8:'Mage',9:'Warlock',11:'Druid'};
 const availability={now:'Saved checks pass',check:'Requirements to check',soon:'Soon',later:'Later'};
 const sourceLabels={owned:'Already owned',guild:'Guild bank',quest:'Quest reward',craft:'Crafting',vendor:'Vendor'};
 let session=null,data=null,serial=0,controller=null,busy=false,sessionBusy=false,fingerprint='',shown=new Map(),activityLimit=6;
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const number=n=>Number(n).toLocaleString(undefined,{maximumFractionDigits:2});
 const currency=n=>{n=Math.ceil(Number(n));return Math.floor(n/10000)+'g '+Math.floor(n%10000/100)+'s '+n%100+'c';};
 const sourceLabel=source=>source.kind==='vendor'?source.name+' · '+currency(source.cost)+' / '+source.buy_count+' item(s)':source.label;
 const label=key=>key.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
 function error(message){$('planner-error').textContent=message||'';$('planner-error').hidden=!message;}
 function pill(text,cls=''){return el('span',text,'planner-pill '+cls);}
 function link(text,url){const a=el('a',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
 let itemTooltipAnchor=null;
 function hideItemTooltip(){itemTooltipAnchor?.removeAttribute('aria-describedby');itemTooltipAnchor=null;$('planner-item-tooltip').hidden=true;}
 function itemLink(item){
  const a=wowheadLink(item.name,'item',item.id);
  const detail=item.level!==undefined?item:data?.characters.flatMap(c=>[...c.equipment.filter(s=>s.item).map(s=>s.item),...c.recommendations.map(r=>r.item)]).find(i=>i.id===item.id);
  if(!detail)return a;
  const tip=$('planner-item-tooltip');
  const show=event=>{hideItemTooltip();itemTooltipAnchor=a;ItemTooltip.render(tip,detail);tip.hidden=false;a.setAttribute('aria-describedby',tip.id);ItemTooltip.position(tip,a,event&&event.type!=='focus'?event:null);};
  a.addEventListener('mouseenter',show);a.addEventListener('focus',show);
  a.addEventListener('mousemove',event=>{if(tip.hidden)show(event);else ItemTooltip.position(tip,a,event);});
  a.addEventListener('mouseleave',hideItemTooltip);a.addEventListener('blur',hideItemTooltip);
  return a;
 }
 window.addEventListener('resize',hideItemTooltip);document.addEventListener('scroll',hideItemTooltip,true);
 document.addEventListener('keydown',event=>{if(event.key==='Escape')hideItemTooltip();});
 function sourceLink(source){if(source.kind==='vendor')return wowheadLink(sourceLabel(source),'npc',source.npc);if(source.kind==='quest')return questLinks(source.label,source.id);if(source.kind==='craft')return wowheadLink(source.label,'spell',source.id);return el('span',sourceLabel(source));}
 function icon(item){const img=el('img',undefined,'planner-item-icon');img.alt='';img.loading='lazy';img.src=item.icon?'/icons/'+encodeURIComponent(item.icon)+'.jpg':'/item-placeholder.svg';img.addEventListener('error',()=>{if(!img.src.endsWith('/item-placeholder.svg'))img.src='/item-placeholder.svg';});return img;}
 async function request(url,options={}){const response=await fetch(url,{cache:'no-store',...options});const payload=await response.json();if(!response.ok||payload.ok===false)throw new Error(payload.error||'Planner unavailable. Try refreshing.');return payload;}
 function group(){return session?.groups.groups.find(g=>g.id===session.groups.selected);}
 function renderGroups(){
  const select=$('planner-group');select.replaceChildren();
  for(const g of session?.groups.groups||[]){const option=el('option',g.name+' ('+g.members.length+')');option.value=g.id;select.append(option);}
  if(!select.children.length)select.append(el('option','No groups yet'));
  else select.value=session.groups.selected;
  select.disabled=busy||!select.children.length||!group();
 }
 async function readSession(force=false){
  if(sessionBusy||busy)return;sessionBusy=true;
  try{const latest=await request('/api/session');const next=JSON.stringify(latest.groups);session=latest;renderGroups();if(force||next!==fingerprint){fingerprint=next;shown.clear();await load();}}
  catch(e){error(e.message);}finally{sessionBusy=false;}
 }
 function matches(rec){const source=$('planner-source').value,when=$('planner-availability').value;return (!source||(source==='owned'?['owned','guild'].includes(rec.source.kind):rec.source.kind===source))&&(!when||rec.availability===when);}
 function statTable(values,contributions=null){
  const table=el('table',undefined,'planner-stat-table'),head=el('tr');
  for(const text of contributions?['Stat change','Amount','Score contribution']:['Stat','Amount']){const th=el('th',text);th.scope='col';head.append(th);}const thead=el('thead');thead.append(head);table.append(thead);const body=el('tbody');
  for(const [key,value] of Object.entries(values).sort((a,b)=>a[0].localeCompare(b[0]))){if(!value)continue;const row=el('tr'),amount=el('td',(contributions&&value>0?'+':'')+number(value),contributions?(value>0?'planner-positive':'planner-negative'):'');row.append(el('td',label(key)),amount);if(contributions){const score=contributions[key]||0;row.append(el('td',(score>0?'+':'')+number(score)));}body.append(row);}table.append(body);return table;
 }
 function recommendation(rec){
  const details=el('details',undefined,'planner-upgrade'),summary=el('summary'),copy=el('div',undefined,'planner-item-copy'),gain=el('div','+'+number(rec.gain),'planner-gain');
  gain.append(el('small',rec.gain_percent===null?'empty-slot score':number(rec.gain_percent)+'% score gain'));
  const name=el('strong',undefined,'planner-quality-'+rec.item.quality);name.append(itemLink(rec.item));const source=el('small',rec.slot_name+' · ');source.append(sourceLink(rec.source));copy.append(name,source);
  const tags=el('div');tags.append(pill(sourceLabels[rec.source.kind],['owned','guild'].includes(rec.source.kind)?'owned':''),pill(availability[rec.availability],rec.availability));if(rec.confidence==='review')tags.append(pill('Review effects','review'));copy.append(tags);
  summary.append(icon(rec.item),copy,gain);details.append(summary);const content=el('div',undefined,'planner-upgrade-detail');
  const replaced=el('p','Replaces: ');if(rec.replaced_items?.length)rec.replaced_items.forEach((item,i)=>{if(i)replaced.append(document.createTextNode(' + '));replaced.append(itemLink(item));});else replaced.append(document.createTextNode(rec.replaces.join(' + ')));
  content.append(itemLink(rec.item),replaced,el('p','Weighted score '+number(rec.baseline_score)+' → '+number(rec.score)+' · Item level '+rec.item.level+' · Requires level '+rec.item.required_level));
  if(rec.item.required_skill){const p=el('p','Requires ','planner-requirements');p.append(wowheadLink('skill #'+rec.item.required_skill,'skill',rec.item.required_skill),document.createTextNode(' at '+rec.item.required_skill_rank));content.append(p);}
  if(rec.source.kind==='quest')content.append(questLinks('Source: '+sourceLabel(rec.source),rec.source.id));else if(rec.source.url)content.append(link('Source: '+sourceLabel(rec.source),rec.source.url));else content.append(el('p','Find it in '+rec.source.label));
  if(rec.source.kind==='craft'){content.append(el('p',(rec.source.learned?'Recipe known':'Recipe acquisition unverified')+' · Required profession skill '+rec.source.required_skill));const materials=el('ul',undefined,'planner-notes');for(const material of rec.source.reagents){const row=el('li');row.append(link(material.name,'https://www.wowhead.com/wotlk/item='+material.id),document.createTextNode(' · '+material.owned+'/'+material.required+' in crafter’s bags'));materials.append(row);}content.append(materials);}
  if(rec.source.kind==='vendor')content.append(el('p','Vendor #'+rec.source.npc+(rec.source.map!==null?' · Map '+rec.source.map+' · World coordinates '+number(rec.source.x)+', '+number(rec.source.y):' · Spawn location unavailable')));
  if(rec.source.kind==='quest'&&rec.source.eligibility&&typeof rec.source.eligibility==='object')content.append(el('p','Class and faction checked: '+rec.source.eligibility.faction+' · '+rec.source.eligibility.class,'planner-requirements'));
  if(rec.source.kind==='quest')content.append(el('p',rec.source.zone+' · Quest level '+rec.source.quest_level+(rec.source.suggested_players?' · '+rec.source.suggested_players+' players suggested':'')));
  content.append(statTable(rec.delta,rec.contributions));
  if(rec.competes_with.length)content.append(el('p','The same item is also suggested for '+rec.competes_with.join(', ')+'. Only one character can use this copy.','planner-requirements'));
  if(rec.notes.length){const notes=el('ul',undefined,'planner-notes');for(const note of rec.notes)notes.append(el('li',note));content.append(notes);}details.append(content);return details;
 }
 function equipment(char){
  const details=el('details',undefined,'planner-equipment');details.append(el('summary','Current saved equipment · '+char.equipment.filter(s=>s.item).length+' occupied slots'));const grid=el('div',undefined,'planner-equipment-grid');
  for(const slot of char.equipment){const card=el('div',undefined,'planner-equipment-slot');card.append(el('span',slot.label));if(slot.item){const row=el('div',undefined,'planner-equipment-item');row.append(icon(slot.item),itemLink(slot.item));card.append(row,el('p','Item level '+slot.item.level+' · Requires level '+slot.item.required_level));const stats=el('details');stats.append(el('summary','Stats and restrictions'),statTable(slot.item.stats));if(slot.item.required_skill)stats.append(el('p','Requires skill #'+slot.item.required_skill+' at '+slot.item.required_skill_rank));if(slot.item.class_mask>0)stats.append(el('p','Class restriction mask: '+slot.item.class_mask));if(slot.item.race_mask>0)stats.append(el('p','Race restriction mask: '+slot.item.race_mask));for(const note of slot.item.notes)stats.append(el('p',note));card.append(stats);}else card.append(el('p','Empty slot'));grid.append(card);}details.append(grid);return details;
 }
 async function setRole(char,select){
  if(busy)return;busy=true;error('');renderGroups();document.querySelectorAll('.planner-role-control select').forEach(n=>n.disabled=true);
  try{await request('/api/gear-planner/role',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':session.token},body:JSON.stringify({guid:char.guid,role:select.value})});shown.delete(char.guid);await load();$('planner-group-status').textContent='Combat role saved only in this dashboard.';}
  catch(e){select.value=char.role;error(e.message);}finally{busy=false;renderGroups();document.querySelectorAll('.planner-role-control select').forEach(n=>n.disabled=false);document.getElementById(select.id)?.focus({preventScroll:true});}
 }
 function member(char){
  const section=el('section',undefined,'panel planner-member'),head=el('header',undefined,'planner-member-heading'),title=el('div');title.append(el('h2',char.name),el('p',char.found?'Level '+char.level+' '+(classes[char.class]||'Class #'+char.class):'Character not found in saved data'));head.append(title);section.append(head);
  if(!char.found){section.append(el('p','This group member remains in the planner. Check the saved name and database connection.','planner-quiet'));return section;}
  const role=el('div',undefined,'planner-role-control'),select=el('select'),roleLabel=el('label','Intended combat role');select.id='planner-role-'+char.guid;roleLabel.htmlFor=select.id;const blank=el('option','Choose a role…');blank.value='';select.append(blank);
  for(const [id,name] of Object.entries(data.roles)){const option=el('option',name);option.value=id;select.append(option);}select.value=char.role;select.disabled=busy;select.addEventListener('change',()=>setRole(char,select));role.append(roleLabel,select);head.append(role);
  const body=el('div',undefined,'planner-member-body');if(!char.role)body.append(el('p','Choose the role you intend to play. Gear is shown below; recommendations wait for your choice.','planner-role-prompt'));
  body.append(equipment(char));
  if(char.role){const matchesList=char.recommendations.filter(matches),limit=shown.get(char.guid)||6;body.append(el('p',matchesList.length+' displayed-source alternatives'+(char.recommendation_count>char.recommendations.length?' · '+char.recommendation_count+' total; best 120 retained per character':'')+' · Alternatives may replace the same slot.','planner-quiet'));
   if(!matchesList.length)body.append(el('p','No worthwhile upgrades match these filters and the five-level lookahead. Try a lower minimum gain or another source.','planner-quiet'));
   const cards=el('div',undefined,'planner-recommendations');for(const rec of matchesList.slice(0,limit))cards.append(recommendation(rec));body.append(cards);
   if(matchesList.length>limit){const more=el('button','Show '+Math.min(matchesList.length-limit,6)+' more alternatives','subtle-button planner-show-more');more.type='button';more.addEventListener('click',()=>{shown.set(char.guid,limit+6);renderMembers();});body.append(more);}
  }
  const method=el('details',undefined,'planner-weights');method.append(el('summary','Role weights used for this character'));if(char.role)method.append(statTable(char.weights||{}));else method.append(el('p','No role is assumed from class or talents.'));body.append(method);section.append(body);return section;
 }
 function renderMembers(){hideItemTooltip();$('planner-members').replaceChildren(...data.characters.map(member));}
 function activityHeading(activity){const h=el('h3');if(activity.kind==='vendor')h.append(wowheadLink(activity.title,'npc',activity.key.split(':')[1]));else if(activity.kind==='quest')h.append(questLinks(activity.title,activity.key.split(':')[1]));else h.textContent=activity.title;return h;}
 function renderActivities(){
  hideItemTooltip();
  $('planner-plan-title').textContent=data.characters.length===1?'Your next worthwhile steps':'The next worthwhile steps';const container=$('planner-activities');container.replaceChildren();
  const source=$('planner-source').value,when=$('planner-availability').value,activities=data.activities.filter(a=>!source||(source==='owned'?['owned','guild'].includes(a.kind):a.kind===source)).map(a=>{const beneficiaries=a.beneficiaries.filter(b=>!when||b.availability===when);return {...a,beneficiaries,members:beneficiaries.length};}).filter(a=>a.members);
  for(const activity of activities.slice(0,activityLimit)){const card=el('article',undefined,'planner-activity');card.append(pill(sourceLabels[activity.kind],['owned','guild'].includes(activity.kind)?'owned':''),activityHeading(activity),el('p',activity.members+' group '+(activity.members===1?'member benefits':'members benefit')));const list=el('ul');for(const row of activity.beneficiaries){const li=el('li');li.append(el('strong',row.character),itemLink(row.item_details||{id:row.item_id,name:row.item}),document.createTextNode(' · +'+number(row.gain)+' score'),el('p',availability[row.availability]));list.append(li);}if(activity.location)card.append(el('p',activity.location));card.append(el('p',activity.effort+' estimated effort · Relative group gains and number of members determine value.'),list,el('p',activity.notes));container.append(card);}
  if(activities.length>activityLimit){const more=el('button','Show all '+activities.length+' activities','subtle-button planner-activity-more');more.type='button';more.addEventListener('click',()=>{activityLimit=activities.length;renderActivities();});container.append(more);}
  if(!activities.length)container.append(el('p',data.characters.some(c=>c.role)?'No fully scored activities match this source yet. Check the individual alternatives, including items whose effects need review.':'Set each character’s intended role below to rank the group’s opportunities.','planner-quiet'));
 }
 function render(){
  $('planner-empty').hidden=!!data.group;$('planner-content').hidden=!data.group;
  $('planner-warnings').replaceChildren(...data.warnings.map(note=>el('p',note)));
  $('planner-refreshed').textContent='Saved snapshot '+new Date(data.refreshed_at).toLocaleTimeString();
  if(!data.group)return;
  $('planner-scope').textContent=data.scope+' '+data.owner_count+' owner characters searched.';$('planner-coverage').textContent=data.coverage;
  renderActivities();renderMembers();
 }
 async function load(){
  const requestId=++serial;controller?.abort();controller=new AbortController();const activeController=controller,signal=controller.signal;
  if(data?.group?.id!==group()?.id){data=null;$('planner-content').hidden=true;$('planner-empty').hidden=true;}error('');$('planner-refresh').disabled=true;$('planner-refreshed').textContent='Reading saved gear and sources…';
  const timeout=setTimeout(()=>activeController.abort(),60000);
  try{const result=await request('/api/gear-planner?threshold='+$('planner-threshold').value,{signal});if(requestId!==serial)return;data=result.result;render();}
  catch(e){if(e.name!=='AbortError'&&requestId===serial)error(e.message);}
  finally{clearTimeout(timeout);if(requestId===serial)$('planner-refresh').disabled=false;}
 }
 $('planner-group').addEventListener('change',async()=>{if(busy)return;busy=true;const previous=session.groups.selected;$('planner-group').disabled=true;try{const response=await request('/api/groups',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':session.token},body:JSON.stringify({action:'select',id:$('planner-group').value})});session.groups=response.groups;fingerprint=JSON.stringify(response.groups);shown.clear();await load();$('planner-group-status').textContent='Shared group selection saved.';}catch(e){$('planner-group').value=previous;error(e.message);}finally{busy=false;renderGroups();}});
 for(const id of ['planner-source','planner-availability'])$(id).addEventListener('change',()=>{if(data?.group){renderActivities();renderMembers();}});
 $('planner-threshold').addEventListener('change',()=>{shown.clear();load();});$('planner-refresh').addEventListener('click',()=>readSession(true));
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)readSession();});window.addEventListener('pageshow',e=>{if(e.persisted)readSession(true);});
 setInterval(()=>{if(!document.hidden)readSession();},2000);readSession(true);
})();
