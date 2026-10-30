'use strict';
(() => {
 const $=id=>document.getElementById(id),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const groups=[['available','Available Now'],['soon','Coming Soon'],['later','Not Yet Available'],['blocked','Other Requirements'],['known','Already Learned']];
 let session=null,request=0,controller=null,timer=null,tooltipAnchor=null,groupBusy=false;
 function hideTooltip(){tooltipAnchor?.removeAttribute('aria-describedby');tooltipAnchor=null;$('training-tooltip').hidden=true;}
 function currency(value){const g=Math.floor(value/10000),s=Math.floor(value%10000/100),c=value%100;return [[g,'g'],[s,'s'],[c,'c']].filter(([n])=>n).map(([n,k])=>n+k).join(' ')||'No charge';}
 function showTooltip(target,ability,event){
  hideTooltip();tooltipAnchor=target;const tip=$('training-tooltip');
  const head=el('div',undefined,'tooltip-heading');head.append(icon(ability),el('h3',ability.name,'training-tooltip-name'));tip.replaceChildren(head);
  const line=(text,cls)=>tip.append(el('p',text,cls));
  if(ability.rank)line(ability.rank,'training-tooltip-rank');
  if(ability.passive)line('Passive');
  else {if(ability.power_cost)line(ability.power_cost);if(ability.cast_time_ms!==null&&ability.cast_time_ms!==undefined)line(ability.cast_time_ms===0?'Instant':ability.cast_time_ms/1000+' sec cast');if(ability.range_yards)line(ability.range_yards+' yd range');if(ability.cooldown_ms)line('Cooldown: '+(ability.cooldown_ms>=60000?ability.cooldown_ms/60000+' min':ability.cooldown_ms/1000+' sec'));}
  line('Requires Level '+ability.required_level,'training-requirement');
  if(ability.description)line(ability.description,'training-description');
  if(!ability.description_complete)line('Some values depend on your character or the game client; placeholders are not estimates.','training-tooltip-note');
  if(ability.cost_scales)line('Base power cost; level modifiers are not simulated.','training-tooltip-note');
  for(const note of ability.requirements||[])line(note,'training-requirement');
  line('Base training cost: '+currency(ability.base_cost),'training-tooltip-price');line('Saved spellbook · Trainer scripts and discounts may differ.','training-tooltip-note');
  ItemTooltip.layout(tip);tip.hidden=false;target.setAttribute('aria-describedby',tip.id);ItemTooltip.position(tip,target,event?.type.startsWith('mouse')?event:null);
 }
 function icon(ability){const img=el('img');img.alt='';img.loading='lazy';img.src=ability.icon?'/icons/'+encodeURIComponent(ability.icon)+'.jpg':'/item-placeholder.svg';img.addEventListener('error',()=>{if(!img.src.endsWith('/item-placeholder.svg'))img.src='/item-placeholder.svg';});return img;}
 function attach(target,ability){target.addEventListener('mouseenter',e=>showTooltip(target,ability,e));target.addEventListener('focus',()=>showTooltip(target,ability));target.addEventListener('click',()=>showTooltip(target,ability));target.addEventListener('mousemove',e=>{if($('training-tooltip').hidden)showTooltip(target,ability,e);else ItemTooltip.position($('training-tooltip'),target,e);});target.addEventListener('mouseleave',()=>{if(document.activeElement!==target)hideTooltip();});target.addEventListener('blur',hideTooltip);}
 function selectedGroup(){return session?.groups.groups.find(g=>g.id===session.groups.selected);}
 function renderCharacters(){const group=selectedGroup();$('training-characters').replaceChildren(...(group?.members||[]).map(name=>{const button=el('button',name);button.type='button';button.setAttribute('aria-pressed',String(name.toLowerCase()===$('training-name').value.toLowerCase()));button.addEventListener('click',()=>{$('training-name').value=name;renderCharacters();load();});return button;}));}
 function error(message){$('training-error').textContent=message||'';$('training-error').hidden=!message;}
 function restoreURL(){const p=new URLSearchParams(location.search);$('training-name').value=p.get('name')||'';$('training-search').value=p.get('q')||'';$('training-level').value=p.get('level')||'';$('training-mode').value=['upcoming','unlearned','available','all'].includes(p.get('mode'))?p.get('mode'):'upcoming';}
 function render(data){
  hideTooltip();$('training-empty').hidden=true;$('training-book').hidden=false;
  const c=data.character;$('training-owner').textContent=c.name+' · Level '+c.level+' '+c.class_name;
  $('training-summary').textContent=data.abilities.length+' shown · '+(data.counts.soon+data.counts.later)+' upcoming · '+data.counts.available+' available now · '+data.counts.known+' learned';
  $('training-refreshed').textContent='Last successful refresh: '+new Date(data.refreshed_at).toLocaleTimeString();
  $('training-warning').textContent=data.warning||'';$('training-warning').hidden=!data.warning;
  const list=$('training-list');list.replaceChildren();
  for(const [state,title] of groups){const abilities=data.abilities.filter(a=>a.state===state);if(!abilities.length)continue;
   const section=el('section',undefined,'training-section '+state);section.append(el('h3',title));
   for(const a of abilities){const row=el('div',undefined,'training-row '+state+(a.state==='later'&&a.required_level-c.level<=4?' near':''));const button=el('button',undefined,'training-ability');button.type='button';
    const name=el('span',undefined,'training-ability-name');name.append(document.createTextNode(a.name));if(a.rank||a.passive)name.append(el('span',' ('+[a.rank,a.passive?'Passive':''].filter(Boolean).join(' · ')+')','training-rank'));
    button.append(icon(a),name,el('span','Level '+a.required_level,'training-level'));button.setAttribute('aria-label',a.name+(a.rank?' '+a.rank:'')+' · Level '+a.required_level);attach(button,a);
    const link=wowheadLink('↗','spell',a.id);link.classList.add('wowhead-shortcut');link.setAttribute('aria-label','View '+a.name+' on Wowhead');row.append(button,link);section.append(row);
   }list.append(section);
  }
  if(!data.abilities.length)list.append(el('p','No abilities match these filters. Try another level, clear the search, or choose All unlearned.','training-no-results'));
 }
 async function load(){
  const current=++request;controller?.abort();hideTooltip();error('');$('training-refresh').disabled=false;const name=$('training-name').value.trim();
  if(!name){$('training-book').hidden=true;$('training-empty').hidden=false;$('training-refreshed').textContent='Choose a character';return;}
  if(!/^[A-Za-z]{2,12}$/.test(name)){error('Enter an existing character name using 2–12 letters.');$('training-book').hidden=true;return;}
  const params=new URLSearchParams({name,mode:$('training-mode').value});if($('training-search').value.trim())params.set('q',$('training-search').value.trim());if($('training-level').value.trim())params.set('level',$('training-level').value.trim());
  history.replaceState(null,'','/training?'+params);controller=new AbortController();const own=controller,timeout=setTimeout(()=>own.abort(),15000);$('training-refresh').disabled=true;$('training-refreshed').textContent='Loading saved training…';$('training-book').hidden=true;
  try{const response=await fetch('/api/training?'+params,{cache:'no-store',signal:own.signal});const payload=await response.json();if(current!==request)return;if(!response.ok||!payload.ok)throw new Error(payload.error||'Training unavailable.');render(payload.result);}
  catch(e){if(current===request){error(e.name==='AbortError'?'Training request timed out. Try refreshing.':e.message);$('training-refreshed').textContent='Training unavailable';}}
  finally{clearTimeout(timeout);if(current===request)$('training-refresh').disabled=false;}
 }
 $('training-character-form').addEventListener('submit',e=>{e.preventDefault();renderCharacters();load();});$('training-filters').addEventListener('submit',e=>{e.preventDefault();clearTimeout(timer);load();});
 $('training-search').addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(load,250);});$('training-level').addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(load,350);});$('training-mode').addEventListener('change',load);$('training-refresh').addEventListener('click',load);
 $('training-reset').addEventListener('click',()=>{clearTimeout(timer);$('training-search').value='';$('training-level').value='';$('training-mode').value='upcoming';load();});
 $('training-group').addEventListener('change',async()=>{
  if(!session||groupBusy)return;groupBusy=true;$('training-group').disabled=true;
  try{const response=await fetch('/api/groups',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':session.token},body:JSON.stringify({action:'select',id:$('training-group').value})});const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||'Cannot select group.');session.groups=result.groups;$('training-name').value=selectedGroup()?.members[0]||'';renderCharacters();await load();$('training-group-status').textContent='Group selection saved.';}
  catch(e){$('training-group').value=session.groups.selected;error(e.message);}finally{groupBusy=false;$('training-group').disabled=false;}
 });
 window.addEventListener('resize',hideTooltip);document.addEventListener('scroll',hideTooltip,true);document.addEventListener('keydown',e=>{if(e.key==='Escape')hideTooltip();});window.addEventListener('popstate',()=>{restoreURL();renderCharacters();load();});
 async function init(){restoreURL();try{const response=await fetch('/api/session',{cache:'no-store'});if(!response.ok)throw new Error('Could not load saved groups.');session=await response.json();const select=$('training-group');select.replaceChildren(...session.groups.groups.map(g=>{const o=el('option',g.name);o.value=g.id;return o;}));select.disabled=!session.groups.groups.length;if(select.disabled){const o=el('option','No saved groups');select.append(o);}else select.value=session.groups.selected;if(!$('training-name').value)$('training-name').value=selectedGroup()?.members[0]||'';renderCharacters();await load();}catch(e){error(e.message);}}
 init();
})();
