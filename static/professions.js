'use strict';
const $=id=>document.getElementById(id);
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
const slotNames={0:'Other / not equipped',1:'Head',2:'Neck',3:'Shoulders',4:'Shirt',5:'Chest',6:'Waist',7:'Legs',8:'Feet',9:'Wrists',10:'Hands',11:'Finger',12:'Trinket',13:'One-hand weapon',14:'Shield',15:'Ranged',16:'Back',17:'Two-hand weapon',18:'Bag',19:'Tabard',20:'Robes (chest)',21:'Main hand',22:'Off hand',23:'Held in off hand',25:'Thrown',26:'Ranged',28:'Relic'};
const params=new URLSearchParams(location.search);
let groupConfig=null,token=null,summary=null,recipeData=null,currentName=/^[A-Za-z]{2,12}$/.test(params.get('name')||'')?params.get('name'):null;
let currentSkill=/^\d{1,5}$/.test(params.get('skill')||'')?Number(params.get('skill')):null;
let mode='learned',selectedRecipe=null,groupBusy=false,groupRequest=0,recipeRequest=0,recipeController=null,browseMining=false;
let professionTooltipAnchor=null;
function hideProfessionTooltip(){professionTooltipAnchor?.removeAttribute('aria-describedby');professionTooltipAnchor=null;$('profession-item-tooltip').hidden=true;}
function attachProfessionTooltip(target,item,recipe=null){
 const tip=$('profession-item-tooltip');
 const show=event=>{
  hideProfessionTooltip();professionTooltipAnchor=target;
  ItemTooltip.render(tip,item,recipe);
  tip.hidden=false;target.setAttribute('aria-describedby',tip.id);ItemTooltip.position(tip,target,event?.type.startsWith('mouse')?event:null);
 };
 if(!target.matches('button,a,input,select'))target.tabIndex=0;
 target.addEventListener('mouseenter',show);target.addEventListener('focusin',show);
 target.addEventListener('mousemove',event=>{if(tip.hidden||professionTooltipAnchor!==target)show(event);else ItemTooltip.position(tip,target,event);});
 target.addEventListener('mouseleave',hideProfessionTooltip);target.addEventListener('focusout',hideProfessionTooltip);
}
window.addEventListener('resize',hideProfessionTooltip);document.addEventListener('scroll',hideProfessionTooltip,true);
document.addEventListener('keydown',event=>{if(event.key==='Escape')hideProfessionTooltip();});
function group(){return groupConfig.groups.find(g=>g.id===groupConfig.selected);}
function error(message){$('prof-error').textContent=message||'';$('prof-error').hidden=!message;}
function character(){return recipeData?.characters[0]||summary?.characters.find(c=>c.name.toLowerCase()===currentName?.toLowerCase());}
function saveURL(){const p=new URLSearchParams();if(currentName)p.set('name',currentName);if(currentSkill)p.set('skill',currentSkill);history.replaceState(null,'','/professions?'+p);}
function icon(path){const img=node('img',null,'recipe-icon');img.alt='';img.width=52;img.height=52;img.src=path?'/icons/'+encodeURIComponent(path)+'.jpg':'/item-placeholder.svg';img.addEventListener('error',()=>{if(!img.src.endsWith('/item-placeholder.svg'))img.src='/item-placeholder.svg';});return img;}
function renderGroup(){
 if(!group()){$('prof-group').disabled=true;$('prof-skill').disabled=true;$('prof-group-status').textContent='Create your first group on the Dashboard to browse professions.';return;}
 $('prof-group').replaceChildren(...groupConfig.groups.map(g=>{const o=node('option',g.name+' ('+g.members.length+')');o.value=g.id;return o;}));$('prof-group').value=groupConfig.selected;
 $('prof-characters').replaceChildren(...group().members.map(name=>{const b=node('button',name);b.type='button';b.disabled=groupBusy||!summary;b.classList.toggle('active',name.toLowerCase()===currentName?.toLowerCase());b.setAttribute('aria-pressed',String(name.toLowerCase()===currentName?.toLowerCase()));b.addEventListener('click',()=>chooseCharacter(name));return b;}));
 $('prof-group').disabled=groupBusy;
}
function renderSummary(){
 $('prof-summary-grid').classList.toggle('short-summary',summary.characters.length<3);
 $('prof-summary-title').textContent=group().name+' · Profession levels';
 $('prof-summary-grid').replaceChildren(...summary.characters.map(c=>{
  const card=node('section',null,'profession-summary-card');card.append(node('h3',c.name));
  const skills=c.skills.filter(s=>s.profession);
  if(!c.found)card.append(node('p','No saved character found.','profession-help'));
  else if(!skills.length)card.append(node('p','No saved professions learned.','profession-help'));
  else for(const skill of skills)card.append(window.CharacterHubSkills.bar(skill,false));
  return card;
 }));
}
function renderSkillOptions(){
 const c=character();if(!c)return;
 const skills=summary.professions,learned=new Set(c.skills.filter(s=>s.profession).map(s=>s.id));
 const ordered=[...skills].sort((a,b)=>Number(learned.has(b.id))-Number(learned.has(a.id))||Number(a.category!==11)-Number(b.category!==11)||a.name.localeCompare(b.name));
 if(!currentSkill||!skills.some(s=>s.id===currentSkill))currentSkill=ordered[0]?.id;
 $('prof-skill').replaceChildren(...ordered.map(s=>{const o=node('option',s.name+(learned.has(s.id)?'':' · Not learned'));o.value=s.id;return o;}));
 $('prof-skill').value=currentSkill||'';$('prof-skill').disabled=groupBusy||!c.found;
 $('prof-character-label').textContent=c.found?c.name+' · Saved level '+c.level:c.name+' · Character not found';
}
function chooseCharacter(name){
 if(groupBusy||!summary)return;
 currentName=name;recipeData=null;selectedRecipe=null;browseMining=false;
 const c=summary?.characters.find(c=>c.name.toLowerCase()===name.toLowerCase());
 if(c&&!c.skills.some(s=>s.id===currentSkill&&s.profession))currentSkill=c.skills.find(s=>s.profession)?.id||null;
 renderGroup();renderSkillOptions();loadRecipes(true);
}
async function loadGroup(reset=false){
 const request=++groupRequest;if(!groupConfig)return;
 if(!group()){$('profession-window').hidden=true;$('prof-summary-title').textContent='No group selected';return;}
 $('prof-refresh').disabled=true;
 if(reset){++recipeRequest;recipeController?.abort();summary=null;recipeData=null;$('profession-window').hidden=true;$('prof-summary-grid').replaceChildren();$('prof-skill').disabled=true;}
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
 try{
  const response=await fetch('/api/skills?names='+encodeURIComponent(group().members.join(',')),{cache:'no-store',signal:controller.signal});const payload=await response.json();
  if(request!==groupRequest)return;if(!response.ok||!payload.ok)throw new Error(payload.error||'Saved skills unavailable.');
  summary=payload.result;
  if(!currentName)currentName=group().members[0];
  renderGroup();renderSummary();renderSkillOptions();error('');await loadRecipes(reset);
 }catch(e){if(request===groupRequest)error((e.name==='AbortError'?'Skill request timed out.':e.message)+(summary?' Showing the previous successful saved group.':''));}
 finally{clearTimeout(timeout);if(request===groupRequest)$('prof-refresh').disabled=false;}
}
async function loadRecipes(reset=false){
 hideProfessionTooltip();
 if(!currentSkill||!currentName){$('profession-window').hidden=true;return;}
 const request=++recipeRequest;recipeController?.abort();const controller=new AbortController();recipeController=controller;
 const name=currentName,skill=currentSkill,timeout=setTimeout(()=>controller.abort(),15000);
 if(reset){recipeData=null;$('profession-window').hidden=true;}
 saveURL();$('prof-detail').setAttribute('aria-busy','true');
 try{
  const p=new URLSearchParams({name,skill});const response=await fetch('/api/professions?'+p,{cache:'no-store',signal:controller.signal});const payload=await response.json();
  if(request!==recipeRequest||name!==currentName||skill!==currentSkill)return;
  if(!response.ok||!payload.ok)throw new Error(payload.error||'Recipes unavailable.');
  recipeData=payload.result;renderSkillOptions();$('profession-window').hidden=false;error('');
  $('prof-refreshed').textContent='Last successful refresh: '+new Date(recipeData.refreshed_at).toLocaleString();renderProfession();
 }catch(e){if(request===recipeRequest)error((e.name==='AbortError'?'Recipe request timed out.':e.message)+(recipeData?' Showing the previous successful recipe snapshot.':''));}
 finally{clearTimeout(timeout);if(request===recipeRequest)$('prof-detail').setAttribute('aria-busy','false');}
}
function renderProfession(){
 const c=character(),definition=summary.professions.find(s=>s.id===currentSkill),skill=c.skills.find(s=>s.id===currentSkill);
 $('prof-emblem').replaceChildren(icon(definition.icon));
 $('prof-title').textContent=currentSkill===186&&browseMining?'Smelting':definition.name;$('prof-owner').textContent=c.name;
 $('prof-rank').replaceChildren(window.CharacterHubSkills.bar(skill||{id:currentSkill,name:definition.name+' · Not learned',category:11,value:0,max:0},false));
 const gathering=definition.gathering&&!(currentSkill===186&&browseMining);
 $('prof-gathering').hidden=!gathering;$('prof-recipe-browser').hidden=gathering;
 $('prof-smelting').hidden=currentSkill!==186;
 $('prof-gathering-text').textContent=currentSkill===186?'Mining is a gathering skill. Its saved rank is shown above; browse smelting separately for learned and unlearned crafting recipes.':definition.name+' is a gathering skill. The saved rank is shown above; there is no crafting-recipe catalogue to mark unlearned.';
 const previous=$('prof-subclass').value;
 $('prof-subclass').replaceChildren(node('option','All subclasses'),...[...new Set(recipeData.recipes.map(r=>r.group))].sort().map(name=>{const o=node('option',name);o.value=name;return o;}));$('prof-subclass').firstChild.value='';
 if([...$('prof-subclass').options].some(o=>o.value===previous))$('prof-subclass').value=previous;
 const previousSlot=$('prof-slot').value;
 const slots=[...new Set(recipeData.recipes.map(r=>r.outputs[0]?.slot||0))].sort((a,b)=>(slotNames[a]||'').localeCompare(slotNames[b]||''));
 $('prof-slot').replaceChildren(node('option','All slots'),...slots.map(id=>{const o=node('option',slotNames[id]||'Slot #'+id);o.value=id;return o;}));$('prof-slot').firstChild.value='';
 if([...$('prof-slot').options].some(o=>o.value===previousSlot))$('prof-slot').value=previousSlot;
 $('prof-slot').hidden=slots.length<=1;
 renderRecipes();
}
function renderRecipes(){
 hideProfessionTooltip();
 if(!recipeData)return;
 for(const key of ['learned','unlearned','all'])$('recipes-'+key).setAttribute('aria-pressed',String(mode===key));
 const terms=$('prof-search').value.trim().toLowerCase().split(/\s+/).filter(Boolean),category=$('prof-subclass').value,slot=$('prof-slot').value;
 const recipes=recipeData.recipes.filter(r=>(mode==='all'||(mode==='learned'?r.status!=='unlearned':r.status==='unlearned'))&&(!category||r.group===category)&&(!slot||(r.outputs[0]?.slot||0)===Number(slot))&&(!$('prof-materials').checked||r.has_materials)&&terms.every(t=>(r.name+' '+r.id+' '+r.reagents.map(x=>x.name).join(' ')).toLowerCase().includes(t)));
 const learned=recipeData.recipes.filter(r=>r.status!=='unlearned').length;
 $('prof-recipe-count').textContent=`${recipes.length} shown · ${learned} learned/granted · ${recipeData.recipes.length-learned} unlearned`;
 const list=$('prof-recipes');list.replaceChildren();const groups=new Map();
 if(!recipes.some(r=>r.id===selectedRecipe))selectedRecipe=recipes[0]?.id||null;
 for(const r of recipes){
  let section=groups.get(r.group);if(!section){section=node('details',null,'recipe-group');section.open=true;section.append(node('summary',r.group));list.append(section);groups.set(r.group,section);}
  const button=node('button',null,'recipe-row '+r.difficulty);button.type='button';button.dataset.recipe=r.id;button.setAttribute('aria-pressed',String(r.id===selectedRecipe));
  const count=r.material_count>0&&r.status==='learned'?' ['+r.material_count+']':'';
  button.append(node('span',r.name+(r.rank?' · '+r.rank:'')+count),node('small',r.status==='unlearned'?'Unlearned':r.status==='superseded'?'Replaced':String(r.required_skill)));
  attachProfessionTooltip(button,r.outputs[0],r);
  button.addEventListener('click',()=>{selectedRecipe=r.id;list.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.recipe)===r.id)));renderRecipe(r);});const external=wowheadLink('↗','spell',r.id);external.classList.add('wowhead-shortcut');external.setAttribute('aria-label','View '+r.name+' on Wowhead');const row=node('div',null,'game-record-row');row.append(button,external);section.append(row);
 }
 if(!recipes.length)list.append(node('p','No recipes match this view. Try Unlearned, All recipes, or clear the search.','game-empty'));
 renderRecipe(recipes.find(r=>r.id===selectedRecipe));
}
function recipeTitle(recipe){const h=node('h2');h.append(wowheadLink(recipe.name,'spell',recipe.id));return h;}
function renderRecipe(recipe){
 hideProfessionTooltip();
 const detail=$('prof-detail');detail.replaceChildren();if(!recipe){detail.append(node('p','Select a recipe to inspect its materials.'));return;}
 const title=node('div',null,'recipe-detail-title');title.append(icon(recipe.icon),recipeTitle(recipe));attachProfessionTooltip(title,recipe.outputs[0],recipe);detail.append(title);
 const line=(text,cls)=>detail.append(node('p',text,cls));
 line((recipe.status==='unlearned'?'Unlearned':recipe.status==='superseded'?'Superseded by a learned rank':recipe.learning_source)+' · Requires skill '+recipe.required_skill,'game-detail-note');
 if(recipe.restricted)line('This recipe has class/race restrictions that do not match this character.','recipe-reagent-missing');
 if(recipe.description){const text=recipe.description.replace(/\$[bB]/g,'\n');line(text);if(/\$/.test(text))line('Some formula values in this server text require the live client.','game-detail-note');}
 if(recipe.outputs.length){detail.append(node('h3','Creates'));for(const out of recipe.outputs){const row=node('div',null,'recipe-item');row.append(icon(out.icon),wowheadLink(out.name+' ×'+(out.minimum===out.maximum?out.minimum:out.minimum+'–'+out.maximum),'item',out.id));attachProfessionTooltip(row,out);detail.append(row);}}
 detail.append(node('h3','Reagents'));
 if(!recipe.reagents.length)line('No counted reagents in the server definition.');
 for(const reagent of recipe.reagents){const row=node('div',null,'recipe-item');row.append(icon(reagent.icon));const copy=node('div');const name=node('p');name.append(wowheadLink(reagent.name,'item',reagent.id));copy.append(name,node('p',`${reagent.owned}/${reagent.required} in carried bags`,reagent.owned>=reagent.required?'recipe-reagent-ready':'recipe-reagent-missing'));row.append(copy);attachProfessionTooltip(row,reagent);detail.append(row);}
 if(recipe.tools.length||recipe.tool_categories.length||recipe.focus){detail.append(node('h3','Tools & workstation'));for(const tool of recipe.tools){const p=node('p');p.append(wowheadLink(tool.name,'item',tool.id));attachProfessionTooltip(p,tool);detail.append(p);}for(const tool of recipe.tool_categories)line(tool);if(recipe.focus)line(recipe.focus);}
 line('Recipe spell #'+recipe.id+' · Material counts do not check stations, tools, cooldowns, specializations or all learning requirements.','game-detail-note');
}
$('prof-smelting').addEventListener('click',()=>{browseMining=true;renderProfession();});
$('prof-refresh').addEventListener('click',()=>loadGroup());
$('prof-skill').addEventListener('change',()=>{if(groupBusy)return;currentSkill=Number($('prof-skill').value);browseMining=false;selectedRecipe=null;loadRecipes(true);});
for(const key of ['learned','unlearned','all'])$('recipes-'+key).addEventListener('click',()=>{mode=key;selectedRecipe=null;renderRecipes();});
$('prof-search').addEventListener('input',renderRecipes);$('prof-materials').addEventListener('change',renderRecipes);$('prof-subclass').addEventListener('change',renderRecipes);$('prof-slot').addEventListener('change',renderRecipes);
$('prof-group').addEventListener('change',async()=>{
 if(groupBusy)return;groupBusy=true;$('prof-group').disabled=true;$('prof-refresh').disabled=true;
 try{const response=await fetch('/api/groups',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':token},body:JSON.stringify({action:'select',id:$('prof-group').value})});const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||'Cannot select group.');
  groupConfig=result.groups;currentName=group().members.find(n=>n.toLowerCase()===currentName?.toLowerCase())||group().members[0];currentSkill=null;selectedRecipe=null;browseMining=false;renderGroup();await loadGroup(true);$('prof-group-status').textContent='Group selection saved.';
 }catch(e){$('prof-group').value=groupConfig.selected;error(e.message);}
 finally{groupBusy=false;$('prof-group').disabled=false;$('prof-refresh').disabled=false;renderSkillOptions();}
});
async function init(){
 try{const response=await fetch('/api/session',{cache:'no-store'});if(!response.ok)throw new Error('Cannot load saved groups.');const session=await response.json();groupConfig=session.groups;token=session.token;renderGroup();await loadGroup(true);}
 catch(e){error(e.message);$('prof-refresh').disabled=true;}
}
init();
