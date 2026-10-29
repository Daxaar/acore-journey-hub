'use strict';
(() => {
  const $=id=>document.getElementById(id), el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const professions={164:'Blacksmithing',165:'Leatherworking',197:'Tailoring',202:'Engineering'};
  const slots={1:'Head',2:'Neck',3:'Shoulders',4:'Shirt',5:'Chest',6:'Waist',7:'Legs',8:'Feet',9:'Wrists',10:'Hands',11:'Finger',12:'Trinket',13:'One-hand',14:'Shield',15:'Ranged',16:'Back',17:'Two-hand',19:'Tabard',20:'Robe',21:'Main hand',22:'Off hand',23:'Held in off-hand',25:'Thrown',26:'Ranged',28:'Relic'};
  const statNames={0:'Mana',1:'Health',3:'Agility',4:'Strength',5:'Intellect',6:'Spirit',7:'Stamina',12:'Defense rating',13:'Dodge rating',14:'Parry rating',15:'Block rating',16:'Melee hit',17:'Ranged hit',18:'Spell hit',19:'Melee crit',20:'Ranged crit',21:'Spell crit',31:'Hit rating',32:'Crit rating',36:'Haste rating',38:'Attack power',39:'Ranged attack power',43:'Mana per 5',45:'Spell power'};
  let page=0, totalPages=0, requestId=0, detailRequest=0, selected=null, token=null, dirty=false, saving=false;
  const form=$('craft-filters');
  let tooltipAnchor=null;
  function hideTooltip(){tooltipAnchor?.removeAttribute('aria-describedby');tooltipAnchor=null;$('craft-item-tooltip').hidden=true;}
  function itemTooltip(target,item){
    const tip=$('craft-item-tooltip');
    const show=event=>{hideTooltip();tooltipAnchor=target;ItemTooltip.render(tip,item);tip.hidden=false;target.setAttribute('aria-describedby',tip.id);ItemTooltip.position(tip,target,event?.type==='focus'?null:event);};
    target.addEventListener('mouseenter',show);target.addEventListener('focus',show);
    target.addEventListener('mousemove',event=>{if(tip.hidden)show(event);else ItemTooltip.position(tip,target,event);});
    target.addEventListener('mouseleave',hideTooltip);target.addEventListener('blur',hideTooltip);
    return target;
  }
  window.addEventListener('resize',hideTooltip);document.addEventListener('scroll',hideTooltip,true);
  document.addEventListener('keydown',event=>{if(event.key==='Escape')hideTooltip();});
  for(const [value,text] of Object.entries(slots)){const o=el('option',text);o.value=value;$('craft-slot').append(o);}
  async function request(url,options={}){const response=await fetch(url,{cache:'no-store',...options});const data=await response.json();if(!response.ok||data.ok===false)throw new Error(data.error||'Crafting ledger unavailable.');return data;}
  function error(text){$('craft-error').textContent=text;$('craft-error').hidden=!text;}
  function tag(text){const n=el('span',text);n.className='craft-tag';return n;}
  function heading(parent,text){parent.append(el('h3',text));}
  function list(parent,texts){const ul=el('ul');for(const text of texts)ul.append(el('li',text));parent.append(ul);}
  function sourceNode(s){
    const n=el('span');
    if(s.kind==='quest')n.append(questLinks(s.name||'Quest #'+s.id,s.id));
    else if(s.kind==='vendor')n.append(wowheadLink('Vendor #'+s.npc,'npc',s.npc));
    else if(s.kind==='creature loot')n.append(wowheadLink('Creature #'+s.id,'npc',s.id));
    else if(s.kind==='gameobject loot'||s.kind==='item loot')n.append(document.createTextNode(s.kind+' · loot entry #'+s.id));
    else n.append(document.createTextNode(s.kind+' #'+(s.trainer||s.id||'')));
    if(s.kind==='trainer')n.append(document.createTextNode(' · learning rank '+s.skill+' · character level '+s.level));
    if(s.stock)n.append(document.createTextNode(' · limited stock '+s.stock));
    if(s.extended_cost)n.append(document.createTextNode(' · special currency/cost #'+s.extended_cost));
    return n;
  }
  function sources(parent,values,total=values.length){const ul=el('ul');for(const s of values.slice(0,8)){const li=el('li');li.append(sourceNode(s));ul.append(li);}if(total>8)ul.append(el('li',(total-8)+' additional source rows; bounded panels can be reproduced by the extraction tool.'));if(!values.length)ul.append(el('li','Source unresolved; manual verification required.'));parent.append(ul);}
  function statValues(item){const out={};for(const key of ['armor','block','dmg_min1','dmg_max1','dmg_min2','dmg_max2','delay','holy_res','fire_res','nature_res','frost_res','shadow_res','arcane_res'])if(item[key])out[key]=item[key];for(let i=1;i<=10;i++)if(item['stat_value'+i]){const key=statNames[item['stat_type'+i]]||'Stat #'+item['stat_type'+i];out[key]=(out[key]||0)+item['stat_value'+i];}return out;}
  function statTable(original,proposed){const a=statValues(original),b=statValues(proposed),table=el('table');table.className='craft-table';const head=el('thead'),row=el('tr');for(const t of ['Statistic','Original','Proposed','Difference'])row.append(el('th',t));head.append(row);table.append(head);const body=el('tbody');for(const k of new Set([...Object.keys(a),...Object.keys(b)])){const tr=el('tr'),delta=(b[k]||0)-(a[k]||0);for(const v of [k,a[k]||0,b[k]||0,(delta>0?'+':'')+delta])tr.append(el('td',String(v)));body.append(tr);}if(!body.children.length){const tr=el('tr'),td=el('td','No resolved flat statistics. Inspect effects and full templates below.');td.colSpan=4;tr.append(td);body.append(tr);}table.append(body);return table;}
  function renderDetail(result){
    hideTooltip();
    const r=result.item,box=$('craft-detail');selected=r;dirty=false;box.replaceChildren(el('p','THE REVIEW DESK'));box.firstChild.className='eyebrow';
    const title=el('h2');title.append(itemTooltip(wowheadLink(r.name,'item',r.id),r.tooltip));box.append(title,tag(r.scope==='initial'?'Initial 1–30 · acquisition must be checked':r.scope==='future'?'Future 31–60':'Level-60 endgame'),tag(r.assessment));
    box.append(el('p','Equip level '+r.baseline.RequiredLevel+' · item level '+r.baseline.ItemLevel+' · '+slots[r.slot]+' · '+r.type));
    if(r.baseline.RequiredSkill){const p=el('p','Profession required to wear: ');p.append(wowheadLink(professions[r.baseline.RequiredSkill]||'Skill #'+r.baseline.RequiredSkill,'skill',r.baseline.RequiredSkill),document.createTextNode(' '+r.baseline.RequiredSkillRank));box.append(p);}
    if(r.baseline.requiredspell){const p=el('p','Required ability: ');p.append(wowheadLink('Spell #'+r.baseline.requiredspell,'spell',r.baseline.requiredspell));box.append(p);}
    if(r.baseline.RequiredReputationFaction){const p=el('p','Required reputation: ');p.append(wowheadLink('Faction #'+r.baseline.RequiredReputationFaction,'faction',r.baseline.RequiredReputationFaction),document.createTextNode(' · rank '+r.baseline.RequiredReputationRank));box.append(p);}
    if(r.focused_panel)box.append(tag('Focused assessment panel · owner review pending'));
    if(r.assessment==='adjustment proposed')box.append(el('p',r.initial_candidate_ready_for_review?'Acquisition estimate fits initial 1–30 review scope; assumptions still need confirmation.':'Acquisition uncertainty prevents treating this as a ready 1–30 pilot candidate.'));
    heading(box,'Realistic crafting availability');box.append(el('p',r.availability.low+'–'+r.availability.high+' · '+r.availability.confidence+' confidence · '+r.availability.scenario));box.append(el('p',r.availability.assumptions),el('p',r.availability.material_effort));
    list(box,r.availability.scenarios.map(s=>s.name+': '+s.low+'–'+(s.high??'unknown')+' · '+s.confidence+' confidence'+(s.assumption?' · '+s.assumption:'')));
    heading(box,'Assessment & proposed differences');list(box,r.reasoning);box.append(statTable(r.baseline,r.proposed));
    box.append(el('p',Object.keys(r.differences).length?'Exact changed template fields: '+Object.entries(r.differences).map(([k,v])=>k+': '+v.original+' → '+v.proposed+' ('+(v.difference>0?'+':'')+v.difference+')').join('; '):'No changes proposed. Original and proposed templates are stored separately.'));
    for(let i=1;i<=5;i++)if(r.baseline['spellid_'+i]){const p=el('p','Effect: ');p.append(wowheadLink('Spell #'+r.baseline['spellid_'+i],'spell',r.baseline['spellid_'+i]),document.createTextNode(' · '+({0:'on use',1:'on equip',2:'chance on hit',4:'soulstone',5:'on use without delay',6:'teaches spell'}[r.baseline['spelltrigger_'+i]]||'special trigger')+' · effect value requires manual review'));box.append(p);}
    const raw=el('details');raw.append(el('summary','Full original / proposed templates'),el('pre',JSON.stringify({original:r.baseline,proposed:r.proposed},null,2)));box.append(raw);
    heading(box,'Recipes, materials & access');
    for(const recipe of r.recipes){const detail=el('details');detail.append(el('summary',professions[recipe.profession]+' · skill '+recipe.required_skill+' · '+recipe.name));const p=el('p');p.append(wowheadLink(recipe.name,'spell',recipe.id));detail.append(p,el('p','DBC rank '+recipe.dbc_skill+' · learning-source rank '+recipe.learning_skill+(recipe.skill_conflict?' · conflicting rank evidence: manual review':'')));
      if(recipe.specialization)detail.append(el('p','Prerequisite ability or specialization needs validation.'));
      sources(detail,recipe.sources,recipe.source_count);
      for(const book of recipe.recipe_items){const p=el('p','Recipe item: ');p.append(wowheadLink(book.name,'item',book.id),document.createTextNode(' · binding '+book.bonding+' · reputation faction '+book.reputation+' / rank '+book.rank));detail.append(p);}
      detail.append(el('p','Workstation: '+(recipe.focus||'none recorded')+' · tool categories: '+(recipe.tool_categories.join(', ')||'none recorded')));
      const materials=el('ul');for(const m of recipe.reagents){const li=el('li');li.append(wowheadLink(m.name,'item',m.id),document.createTextNode(' × '+m.count));const paths=el('details');paths.append(el('summary','Material acquisition evidence'));if(m.effort)paths.append(el('p',m.effort.classification+' · '+m.effort.confidence+' confidence · '+m.effort.note));sources(paths,m.sources,m.source_count);for(const intermediate of m.intermediate_recipes||[]){const p=el('p','Intermediate craft: ');p.append(wowheadLink(intermediate.name,'spell',intermediate.spell),document.createTextNode(' · '));intermediate.inputs.forEach((input,i)=>{if(i)p.append(document.createTextNode(', '));p.append(wowheadLink(input.name,'item',input.id),document.createTextNode(' × '+input.count));});paths.append(p);}li.append(paths);materials.append(li);}detail.append(materials);box.append(detail);
    }
    heading(box,'Alternatives at the acquisition point');box.append(el('p',r.comparison_pool_size+' source-backed alternatives screened; panel balances dominance and trade-offs. Source presence does not prove practical access.'));
    for(const c of r.comparators){const d=el('details'),s=el('summary');s.append(itemTooltip(wowheadLink(c.name,'item',c.id),c.tooltip),document.createTextNode(' · '+c.relation));d.append(s,el('p','Equip '+c.baseline.RequiredLevel+' · '+c.availability_note),statTable(r.baseline,c.baseline));sources(d,c.sources,c.source_count);box.append(d);}
    if(!r.comparators.length)box.append(el('p','No resolved comparator panel. Retain baseline pending manual review.'));
    heading(box,'Limits & uncertainty');list(box,r.limitations);box.append(el('p',r.era.evidence));
    heading(box,'Your review decision');
    if(r.review.stale){const warning=el('p','Catalogue evidence changed since this decision. The saved decision is retained; review the new evidence before reaffirming it.');warning.className='craft-warning';box.append(warning);}
    const rf=el('form'),label=el('label','Decision'),select=el('select');select.id='craft-decision';label.htmlFor=select.id;for(const status of ['not reviewed','approved','rejected','needs adjustment','deferred']){const o=el('option',status);o.value=status;select.append(o);}select.value=r.review.status;
    const nl=el('label','Reasoning / availability corrections'),notes=el('textarea');notes.id='craft-notes';nl.htmlFor=notes.id;notes.maxLength=5000;notes.value=r.review.notes;
    const save=el('button','Save review');save.type='submit';save.id='craft-save';const status=el('p');status.id='craft-save-status';status.setAttribute('role','status');
    rf.append(label,select,nl,notes,save,status);rf.addEventListener('input',()=>{dirty=true;});rf.addEventListener('submit',async e=>{e.preventDefault();saving=true;save.disabled=true;try{if(!token)token=(await request('/api/session')).token;const response=await request('/api/crafting/review',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':token},body:JSON.stringify({id:r.id,status:select.value,notes:notes.value,revision:r.review.revision,fingerprint:r.fingerprint})});r.review=response.review;dirty=false;status.textContent='Review saved · revision '+r.review.revision;await load(false);}catch(e){status.textContent=e.message;}finally{saving=false;save.disabled=false;}});box.append(rf);
    const history=el('details');history.append(el('summary','Review history · latest 50 revisions'));list(history,result.history.map(h=>h.updated+' · '+h.status+' · '+h.notes));box.append(history);
  }
  async function detail(id,focus=false){if(saving)return;if(dirty&&!confirm('Discard unsaved review notes?'))return;const version=++detailRequest;try{const data=await request('/api/crafting?id='+id);if(version!==detailRequest)return;renderDetail(data.result);for(const row of $('craft-rows').children)row.classList.toggle('selected',row.dataset.id===String(id));const url=new URL(location.href);url.searchParams.set('id',id);history.replaceState(null,'',url);if(focus)$('craft-detail').focus();}catch(e){error(e.message);}}
  async function load(updateUrl=true){const version=++requestId;error('');const params=new URLSearchParams(new FormData(form));for(const [k,v] of [...params])if(!v)params.delete(k);params.set('page',page);if(updateUrl){const url=new URL(location.href);url.search=params.toString();if(selected)url.searchParams.set('id',selected.id);history.replaceState(null,'',url);}try{const data=(await request('/api/crafting?'+params)).result;if(version!==requestId)return;totalPages=data.pages;$('craft-count').textContent='· '+data.total+' of '+data.catalogue_total;$('craft-summary').textContent='Global catalogue · independent of character selection';$('craft-empty').hidden=data.available;$('craft-page').textContent=data.pages?'Page '+(page+1)+' of '+data.pages:'No matching items';$('craft-prev').disabled=page===0;$('craft-next').disabled=page+1>=data.pages;const rows=$('craft-rows');hideTooltip();rows.replaceChildren();for(const r of data.items){const tr=el('tr');tr.dataset.id=r.id;tr.classList.toggle('selected',selected?.id===r.id);const item=el('td'),button=el('button',r.name);button.type='button';itemTooltip(button,r.tooltip);button.addEventListener('click',()=>detail(r.id,true));item.append(button,document.createTextNode(' '),wowheadLink('↗','item',r.id),el('small',[...new Set(r.recipes.map(x=>professions[x.profession]))].join(' / ')+' · '+slots[r.slot]));const levels=el('td','Equip '+r.equip_level);levels.append(el('small','Acquire '+r.availability.low+'–'+r.availability.high+' · '+r.availability.confidence),tag(r.scope));const status=el('td',r.assessment);status.append(el('small',r.review.status+(r.review.stale?' · evidence changed':'')));tr.append(item,levels,status);rows.append(tr);}if(data.available&&!data.items.length){const tr=el('tr'),td=el('td','No items match these filters. Try a wider range.');td.colSpan=3;tr.append(td);rows.append(tr);}const provenance=$('craft-provenance');provenance.replaceChildren();for(const [k,v] of Object.entries(data.provenance))if(k!=='schema_fields')provenance.append(el('p',k+': '+(typeof v==='object'?JSON.stringify(v):v)));}catch(e){if(version===requestId)error(e.message);}}
  form.addEventListener('submit',e=>{e.preventDefault();page=0;load();});$('craft-prev').addEventListener('click',()=>{if(page>0){page--;load();}});$('craft-next').addEventListener('click',()=>{if(page+1<totalPages){page++;load();}});$('craft-reset').addEventListener('click',()=>{form.reset();page=0;load();});
  const params=new URLSearchParams(location.search);for(const [k,v] of params)if(form.elements.namedItem(k))form.elements.namedItem(k).value=v;page=Number(params.get('page')||0);if(!Number.isInteger(page)||page<0)page=0;load();if(params.get('id'))detail(Number(params.get('id')));
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
})();
