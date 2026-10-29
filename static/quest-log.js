'use strict';
const $ = id => document.getElementById(id);
const races = {1:'Human',2:'Orc',3:'Dwarf',4:'Night Elf',5:'Undead',6:'Tauren',7:'Gnome',8:'Troll',10:'Blood Elf',11:'Draenei'};
const classes = {1:'Warrior',2:'Paladin',3:'Hunter',4:'Rogue',5:'Priest',6:'Death Knight',7:'Shaman',8:'Mage',9:'Warlock',11:'Druid'};
const states = {ready:'Complete · Ready to hand in',active:'In progress',failed:'Failed',completed:'Handed in',catalogue:'World quest · No character progress',unknown:'Unknown saved status'};
const modeLabels = {active:'Active quests',completed:'Completed quests',all:'World quest catalogue'};
const url = new URLSearchParams(location.search);
const state = {name:/^[A-Za-z]{2,12}$/.test(url.get('name') || '') ? url.get('name') : '',
  mode:['active','completed','all'].includes(url.get('mode')) ? url.get('mode') : 'active',
  classId:Object.hasOwn(classes,url.get('class'))?Number(url.get('class')):0,
  search:(url.get('q') || '').slice(0,100),page:/^\d{1,5}$/.test(url.get('page') || '') ? Math.min(10000,Number(url.get('page'))) : 0,
  selected:/^\d{1,10}$/.test(url.get('id') || '') ? Number(url.get('id')) : null,
  list:null,detail:null,listRequest:0,detailRequest:0,listController:null,detailController:null};
let groupConfig=null,groupToken=null,watchedNames=[],groupBusy=false,watchView=url.get('roster')==='watch';
function node(tag,text,cls) { const n=document.createElement(tag); if (text!=null) n.textContent=text; if(cls) n.className=cls; return n; }
let partyController, partyRequest=0, partyQuestId=null, partyResult=null, partyError='', partyAnchor=null, partyPinned=false, partyHideTimer;
const partyTooltip=$('quest-party-tooltip');
function hideParty() {
  clearTimeout(partyHideTimer);partyTooltip.hidden=true;partyPinned=false;
  partyAnchor?.removeAttribute('aria-describedby');partyAnchor=null;
}
function positionParty() {
  if(!partyAnchor||partyTooltip.hidden)return;
  const box=partyAnchor.getBoundingClientRect(), tip=partyTooltip.getBoundingClientRect();
  const beside=box.right+tip.width+14<=innerWidth;
  partyTooltip.style.left=Math.max(8,Math.min(beside?box.right+6:box.left,innerWidth-tip.width-8))+'px';
  partyTooltip.style.top=Math.max(8,Math.min(beside?box.top:box.bottom+6,innerHeight-tip.height-8))+'px';
}
function renderParty() {
  partyTooltip.replaceChildren();
  if(!partyResult)partyTooltip.append(node('p',partyError||'Loading selected group’s quest status…'));
  else if(!partyResult.group)partyTooltip.append(node('p','No group selected.'));
  else {
    partyTooltip.append(node('strong',partyResult.title),node('div',partyResult.group.name+' · Quest status'));
    if(partyResult.allowed_classes?.length)partyTooltip.append(node('p','Class quest · '+partyResult.allowed_classes.join(', ')+' only','quest-party-restriction'));
    const labels={...states,missing:'Not in quest log · No recorded hand-in',not_found:'Character not found',ineligible_class:'Ineligible · '+partyResult.allowed_classes?.join(', ')+' only'};
    const characters=partyResult.characters.filter(c=>!c.state.startsWith('ineligible'));
    if(!characters.length)partyTooltip.append(node('p',watchView?(partyResult.characters.length?'No eligible characters in Playerbot Watch.':'No playerbots watched. Add characters to Playerbot Watch on the Dashboard.'):'No eligible characters in this group.'));
    for(const c of characters) {
      const row=node('div',null,'quest-party-member'), description=node('span',labels[c.state]||'Unknown saved status','party-state '+c.state);
      row.append(node('b',c.name+(c.level!=null?' · Level '+c.level+' '+(classes[c.class]||''):'')),description);
      if(c.previously_completed&&c.state!=='completed')row.append(node('small','Also handed in previously'));
      partyTooltip.append(row);
    }
    partyTooltip.append(node('small','Saved progress · Missing does not establish quest eligibility.'));
  }
  positionParty();
}
function showParty(anchor,pinned=false) {
  clearTimeout(partyHideTimer);partyAnchor?.removeAttribute('aria-describedby');partyAnchor=anchor;
  const id=Number(anchor.dataset.questId||state.selected);
  if(id!==partyQuestId)loadParty(id);
  partyPinned=pinned;anchor.setAttribute('aria-describedby','quest-party-tooltip');partyTooltip.hidden=false;renderParty();
}
function attachParty(anchor,click=false,hoverTarget=anchor) {
  hoverTarget.addEventListener('mouseenter',()=>showParty(anchor,partyPinned&&partyAnchor===anchor));
  hoverTarget.addEventListener('mouseleave',()=>{if(!partyPinned)partyHideTimer=setTimeout(hideParty,150);});
  anchor.addEventListener('focus',()=>{if(hoverTarget===anchor||anchor.matches(':focus-visible'))showParty(anchor);});
  anchor.addEventListener('blur',()=>{if(!partyPinned)hideParty();});
  if(click)anchor.addEventListener('click',()=>{if(partyPinned&&partyAnchor===anchor)hideParty();else showParty(anchor,true);});
}
partyTooltip.addEventListener('mouseenter',()=>clearTimeout(partyHideTimer));
partyTooltip.addEventListener('mouseleave',()=>{if(!partyPinned)hideParty();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')hideParty();});
document.addEventListener('click',e=>{if(!partyTooltip.contains(e.target)&&!partyAnchor?.contains(e.target))hideParty();});
window.addEventListener('resize',hideParty);
document.addEventListener('scroll',e=>{
  if(partyTooltip.contains(e.target))return;
  if(partyPinned)positionParty();else hideParty();
},true);
function resetParty() {
  partyController?.abort();++partyRequest;partyQuestId=null;partyResult=null;partyError='';hideParty();
  document.querySelectorAll('.quest-entry').forEach(b=>b.removeAttribute('aria-describedby'));
}
async function loadParty(id) {
  partyController?.abort();const request=++partyRequest;partyQuestId=id;partyResult=null;partyError='';
  const controller=new AbortController();partyController=controller;
  const timeout=setTimeout(()=>controller.abort(),15000);
  try {
    const response=await fetch('/api/quest-party?id='+id+(watchView?'&roster=watch':''),{cache:'no-store',signal:controller.signal});
    const payload=await response.json();if(request!==partyRequest)return;
    if(!response.ok||!payload.ok)throw new Error(payload.error||'Group status unavailable.');
    partyResult=payload.result;
  }catch(e){if(request!==partyRequest)return;partyError='Group status unavailable. Refresh the journal to retry.';}
  finally{clearTimeout(timeout);if(request===partyRequest)renderParty();}
}
function gameText(text,c=state.list?.character) {
  return String(text || '').replace(/\$[bB]/g,'\n').replace(/\$[nN]/g,c?.name || '<name>')
    .replace(/\$[rR]/g,races[c?.race] || '<race>').replace(/\$[cC]/g,classes[c?.class] || '<class>')
    .replace(/\$[gG]([^:;]*):([^;]*);/g,(_,male,female)=>c ? (c.gender===1 ? female : male) : `${male} / ${female}`);
}
function money(value) { const n=Math.abs(value || 0);return `${Math.floor(n/10000)}g ${Math.floor(n/100)%100}s ${n%100}c`; }
function error(message) { $('quest-error').textContent=message || ''; $('quest-error').hidden=!message; }
function saveURL() {
  const params=new URLSearchParams({mode:state.mode});
  if(state.mode!=='all') params.set('name',state.name);
  if(watchView)params.set('roster','watch');
  if(state.classId)params.set('class',state.classId);
  if(state.search) params.set('q',state.search);
  if(state.page) params.set('page',state.page);
  if(state.selected) params.set('id',state.selected);
  history.replaceState(null,'','/quest-log?'+params);
}
function context() { return `${state.mode}:${state.mode==='all'?'':state.name.toLowerCase()}:${state.search}:${state.page}:${state.classId}:${watchView}`; }
function updateControls() {
  $('quest-character').value=state.name;
  $('quest-search').value=state.search;
  $('quest-class').value=String(state.classId);
  $('quest-character-form').hidden=state.mode==='all'; $('quest-shortcuts').hidden=state.mode==='all';
  $('quest-browser').setAttribute('aria-labelledby','mode-'+state.mode);
  for(const mode of ['active','completed','all']) {
    const tab=$('mode-'+mode),active=mode===state.mode;
    tab.setAttribute('aria-selected',String(active)); tab.tabIndex=active?0:-1;
  }
  $('quest-owner').textContent=state.mode==='all'?'World catalogue':state.name;
  $('quest-view-label').textContent=modeLabels[state.mode];
  $('quest-context').textContent=state.mode==='all'?'All server quests, independent of any character or quest eligibility. Search titles, story text or an exact quest ID.'
    :state.mode==='completed'?`${state.name} · All recorded hand-ins, including reset repeatable history. Historical counters, chosen rewards and completion dates are not stored.`
    :`${state.name} · Active saved quests, including ready-to-hand-in and failed entries. No automatic polling.`;
  if(state.classId)$('quest-context').textContent+=' '+classes[state.classId]+'-specific quests only.';
  document.querySelectorAll('#quest-shortcuts button').forEach(b=>b.classList.toggle('active',b.textContent.toLowerCase()===state.name.toLowerCase()));
}
function clearDetail(message='Select a quest to read its story.') {
  hideRewardTooltip();state.detail=null; $('quest-detail').setAttribute('aria-busy','false'); $('quest-detail').replaceChildren(node('p',message,'quest-detail-empty')); $('quest-selection').textContent='Select a quest from the journal';
}
function renderList() {
  const result=state.list, container=$('quest-list');container.replaceChildren();
  $('quest-count').textContent=state.mode==='active'&&!state.search?`Quests: ${result.total}/25`:`Quests: ${result.total.toLocaleString()}`;
  $('quest-page').textContent=`Page ${result.page+1} of ${Math.max(1,Math.ceil(result.total/result.page_size))}`;
  $('quest-prev').disabled=state.page===0;
  $('quest-next').disabled=(state.page+1)*result.page_size>=result.total;
  if(!result.quests.length) container.append(node('p',state.search?'No quests match your search.':state.mode==='active'?'No active saved quests.':state.mode==='completed'?'No recorded hand-ins for this character.':'No quests found.','quest-list-empty'));
  const groups=new Map();
  for(const q of result.quests) {
    const categoryKey=String(q.category_id || 0);
    let group=groups.get(categoryKey);
    if(!group) {group=node('details',null,'quest-category');group.open=true;group.append(node('summary',q.category));groups.set(categoryKey,group);container.append(group);}
    const button=node('button',null,`quest-entry ${q.state}`);button.type='button';button.dataset.questId=q.id;
    button.setAttribute('aria-pressed',String(state.selected===q.id));
    const title=node('span',null,'quest-entry-title'),text=node('span',q.title,'quest-entry-text');title.append(text);
    if(q.quest_side==='horde'||q.quest_side==='alliance') {
      const badge=node('img',null,'quest-faction-icon');badge.src='/quest-'+q.quest_side+'.svg';
      badge.alt=q.quest_side==='horde'?'Horde only':'Alliance only';badge.title=badge.alt;badge.width=17;badge.height=20;title.append(badge);
    }
    if(q.state==='ready')title.append(document.createTextNode(' ✓'));
    button.append(title,node('small',q.state==='ready'?'(Complete)':q.state==='completed'?'✓ Handed in':q.state==='failed'?'Failed':`Level ${q.level===-1?'scaling':q.level ?? '?'}`));
    button.addEventListener('click',()=>selectQuest(q.id));const row=node('div',null,'game-record-row'),external=wowheadLink('↗','quest',q.id);external.setAttribute('aria-label','View '+q.title+' on Wowhead');row.append(button,external);group.append(row);
    attachParty(button,false,text);
  }
}
function selectQuest(id) {
  state.selected=id;saveURL();
  document.querySelectorAll('.quest-entry').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.questId)===id)));
  loadDetail();
}
let rewardTooltipAnchor=null;
function hideRewardTooltip(){rewardTooltipAnchor?.removeAttribute('aria-describedby');rewardTooltipAnchor=null;$('reward-item-tooltip').hidden=true;}
function attachRewardTooltip(target,item){
 const tip=$('reward-item-tooltip');
 const show=event=>{hideRewardTooltip();rewardTooltipAnchor=target;ItemTooltip.render(tip,item);tip.hidden=false;target.setAttribute('aria-describedby',tip.id);ItemTooltip.position(tip,target,event&&event.type!=='focus'?event:null);};
 target.tabIndex=0;target.setAttribute('aria-label','Item details: '+item.name);
 target.addEventListener('mouseenter',show);target.addEventListener('focus',show);
 target.addEventListener('mousemove',event=>{if(tip.hidden)show(event);else ItemTooltip.position(tip,target,event);});
 target.addEventListener('mouseleave',hideRewardTooltip);target.addEventListener('blur',hideRewardTooltip);
}
window.addEventListener('resize',hideRewardTooltip);document.addEventListener('scroll',hideRewardTooltip,true);
document.addEventListener('keydown',event=>{if(event.key==='Escape')hideRewardTooltip();});
function renderDetail(result) {
  hideRewardTooltip();
  const q=result.quests[0], c=result.character, pane=$('quest-detail'); pane.replaceChildren();
  const line=(text,cls)=>pane.append(node('p',text,cls));
  const heading=text=>pane.append(node('h3',text));
  const title=node('h2');title.append(questLinks(q.title,q.id));
  pane.append(title,node('span',states[q.state],'quest-state'));
  const partyButton=node('button',watchView?'Playerbot Watch ⓘ':'Group status ⓘ','quest-party-button');partyButton.type='button';
  partyButton.dataset.questId=q.id;
  partyButton.setAttribute('aria-label','Show selected roster’s completion status for '+q.title);
  attachParty(partyButton,true);pane.append(partyButton);
  line(`${q.category} · Quest #${q.id} · Level ${q.level===-1?'scaling':q.level ?? '?'}${q.MinLevel!=null?' · Requires level '+q.MinLevel:''}${q.SuggestedGroupNum?' · '+q.SuggestedGroupNum+' players suggested':''}`,'quest-meta');
  $('quest-selection').textContent=`Quest #${q.id} · ${q.title}`;
  if(!q.template_found) {line('The saved quest record exists, but its world quest definition is missing. Story and reward details are unavailable.');return;}
  line(gameText(q.LogDescription,c));
  if(q.state==='ready' && q.QuestCompletionLog) line(gameText(q.QuestCompletionLog,c));
  heading('Objectives');
  const objectives=node('ul',null,'quest-objectives');
  for(const obj of q.objectives) {
    const numeric=state.mode==='active'&&obj.current!=null;
    const done=numeric&&obj.current>=obj.required;
    const label=obj.kind==='money'?`${money(obj.required)} required${numeric?' · '+money(obj.current)+' saved':''}`
      :gameText(obj.label,c)+(numeric?` — ${obj.current}/${obj.required}`:obj.kind==='event'||obj.kind==='timer'?'':` — ${obj.required} required`);
    const li=node('li',null,done?'objective-done':'');let type,id;if(obj.key.startsWith('target')){id=q['target'+obj.key.slice(6)];type=id<0?'object':'npc';id=Math.abs(id);}else if(obj.key.startsWith('item')){id=q['item_id'+obj.key.slice(4)];type='item';}else if(obj.kind==='reputation'){id=obj.key==='reputation2'?q.RequiredFactionId2:q.faction;type='faction';}li.append(wowheadLink(`${done?'✓ ':''}${label}`,type,id));
    if(obj.note) li.append(node('small',obj.note));objectives.append(li);
  }
  pane.append(objectives);
  if(state.mode!=='active') line(state.mode==='completed'?'This quest was handed in. Objective counts from that run are not recorded.':'Requirements are shown without character progress.','quest-meta');
  if(q.AreaDescription) line(gameText(q.AreaDescription,c));
  if(q.TimeAllowed) line(`Time limit: ${Math.round(q.TimeAllowed/60*10)/10} minutes. Remaining live time is unavailable.`,'quest-meta');
  heading('Description');line(gameText(q.QuestDescription,c)||'No additional story text is stored for this quest.');
  heading('Rewards');
  if(q.base_xp!=null) line(`Experience: ${q.base_xp.toLocaleString()} (base${state.mode==='all'?', at quest level':', at current character level'})`);
  if(q.RewardMoney>0) line(`Money: ${money(q.RewardMoney)} (base)`);
  if(q.RewardMoney<0) line(`Required payment: ${money(q.RewardMoney)}`);
  for(const kind of ['choice','fixed']) {
    const items=q.rewards.filter(i=>i.kind===kind);if(!items.length) continue;
    line(kind==='choice'?'Choose one of these rewards:':'You will receive:');
    const list=node('div',null,'quest-reward-items');
    for(const item of items) {
      const reward=node('div',null,'quest-reward-item'),img=node('img');img.alt='';img.width=40;img.height=40;
      img.src=item.icon?'/icons/'+encodeURIComponent(item.icon)+'.jpg':'/item-placeholder.svg';
      img.addEventListener('error',()=>{if(!img.src.endsWith('/item-placeholder.svg'))img.src='/item-placeholder.svg';});
      const copy=node('span');copy.append(wowheadLink(`${item.name}${item.count>1?' ×'+item.count:''}`,'item',item.id));copy.append(node('small',` · Item #${item.id}`));
      reward.append(img,copy);attachRewardTooltip(reward,item);list.append(reward);
    }pane.append(list);
  }
  for(const spell of q.reward_spells){const p=node('p','Spell: ');p.append(wowheadLink(spell.name,'spell',Math.abs(spell.id)));pane.append(p);}
  for(const rep of q.reputation_rewards){const p=node('p');p.append(wowheadLink(rep.faction,'faction',rep.id),document.createTextNode(`: ${rep.base==null?'reputation reward':(rep.base>=0?'+':'')+rep.base+' reputation (base)'}`));pane.append(p);}
  for(const [key,label] of [['RewardHonor','Base honor'],['RewardTalents','Talent points'],['RewardArenaPoints','Arena points'],['RewardTitle','Title ID']]) if(q[key]) line(`${label}: ${q[key]}`);
  if(q.RewardKillHonor) line(`Honor scaling factor: ${q.RewardKillHonor}`);
  line('Base rewards can change with server rates, level caps, eligibility and character bonuses. Recorded hand-ins do not store the rewards you chose or received.','quest-meta');
  const contacts=result.contacts || [];
  if(contacts.length) {
    heading('Quest givers');
    for(const role of ['Starts','Ends']) {
      const entries=contacts.filter(n=>n.role===role);
      if(entries.length){const p=node('p',role+': ');entries.forEach((n,i)=>{if(i)p.append(document.createTextNode('; '));p.append(wowheadLink(n.name,{NPC:'npc',Object:'object',Item:'item'}[n.type],n.id),document.createTextNode(' ('+n.type+' #'+n.id+')'));});pane.append(p);}
    }
    if(result.contacts_truncated) line('This quest has more contacts than the display limit.','quest-meta');
  }
  if(q.request_text||q.offer_text||q.QuestCompletionLog) {
    const details=node('details');details.append(node('summary','Quest dialogue & completion text'));
    for(const [label,key] of [['Completion log','QuestCompletionLog'],['Before hand-in','request_text'],['Reward dialogue','offer_text']])
      if(q[key]) details.append(node('h3',label),node('p',gameText(q[key],c)));
    pane.append(details);
  }
  const extra=node('details');extra.append(node('summary','Quest requirements & references'));
  const add=text=>extra.append(node('p',text));
  if(q.Flags&4096)add('Daily quest');if(q.Flags&32768)add('Weekly quest');if(q.special_flags&1)add('Repeatable quest');
  if(q.StartItem){const p=node('p');p.append(wowheadLink('Provided quest item #'+q.StartItem,'item',q.StartItem));extra.append(p);}
  if(q.required_skill)add(`Required skill #${q.required_skill} · ${q.required_skill_points} points`);
  if(q.QuestInfoID)add(`Quest type #${q.QuestInfoID}`);
  if(q.AllowableRaces)add(`Allowed race mask: ${q.AllowableRaces}`);
  for(const [label,id] of [['Previous quest',Math.abs(q.previous_quest||0)],['Next quest',q.next_quest||q.RewardNextQuest]]) {
    if(id) {const p=node('p',label+': ');p.append(questLinks('#'+id,id));extra.append(p);}
  }
  if(state.mode==='completed'&&q.reward_record_active===0)add('This saved hand-in record is inactive/reset. It remains part of the recorded history.');
  extra.append(node('p','Quest text uses server templates. World quests retain name/race/class placeholders when no character is selected.','quest-meta'));pane.append(extra);
}
async function loadDetail() {
  const request=++state.detailRequest;state.detailController?.abort();
  const controller=new AbortController();state.detailController=controller;
  const key=context(),id=state.selected,prior=state.detail;
  if(partyQuestId!==id)loadParty(id);
  if(!prior || prior.quests[0].id!==id) clearDetail('Opening the quest…');
  $('quest-detail').setAttribute('aria-busy','true');
  const timeout=setTimeout(()=>controller.abort(),15000);
  try {
    const params=new URLSearchParams({mode:state.mode,id});if(state.classId)params.set('class',state.classId);if(state.mode!=='all')params.set('name',state.name);
    const response=await fetch('/api/quest?'+params,{cache:'no-store',signal:controller.signal});const payload=await response.json();
    if(request!==state.detailRequest||key!==context())return;
    if(!response.ok||!payload.ok)throw new Error(payload.error||'Quest details unavailable.');
    state.detail=payload.result;renderDetail(state.detail);error('');
  }catch(e) {if(request===state.detailRequest&&key===context())error((e.name==='AbortError'?'Quest detail request timed out.':e.message)+(state.detail?' Showing the previous successful quest details.':''));}
  finally {clearTimeout(timeout);if(request===state.detailRequest)$('quest-detail').setAttribute('aria-busy','false');}
}
async function loadList(reset=false) {
  resetParty();
  if(state.mode!=='all'&&!state.name){
    ++state.listRequest;++state.detailRequest;state.listController?.abort();state.detailController?.abort();state.list=null;state.selected=null;
    updateControls();saveURL();error('');clearDetail(watchView?'Add characters to Playerbot Watch on the Dashboard.':'Enter a character name or create a group on the Dashboard.');
    $('quest-list').replaceChildren(node('p',watchView?'No playerbots watched.':'No character selected.','quest-list-empty'));
    $('quest-count').textContent='Quests: —';$('quest-page').textContent='';$('quest-refreshed').textContent='No character selected';
    $('quest-prev').disabled=true;$('quest-next').disabled=true;$('quest-refresh').disabled=false;$('quest-list').setAttribute('aria-busy','false');return;
  }
  const request=++state.listRequest;state.listController?.abort();state.detailController?.abort();++state.detailRequest;
  const controller=new AbortController();state.listController=controller;const key=context();
  $('quest-detail').setAttribute('aria-busy','false');
  updateControls();error('');saveURL();
  if(reset) {state.list=null;clearDetail();$('quest-list').replaceChildren(node('p','Opening the journal…','quest-list-empty'));$('quest-count').textContent='Quests: —';$('quest-refreshed').textContent='Waiting for saved quests';}
  $('quest-refresh').disabled=true;$('quest-list').setAttribute('aria-busy','true');$('quest-prev').disabled=true;$('quest-next').disabled=true;
  const timeout=setTimeout(()=>controller.abort(),15000);
  try {
    const params=new URLSearchParams({mode:state.mode,q:state.search,page:state.page});if(state.classId)params.set('class',state.classId);if(state.mode!=='all')params.set('name',state.name);
    const response=await fetch('/api/quests?'+params,{cache:'no-store',signal:controller.signal});const payload=await response.json();
    if(request!==state.listRequest||key!==context())return;
    if(!response.ok||!payload.ok)throw new Error(payload.error||'Quest list unavailable.');
    state.list=payload.result;
    if(!state.list.quests.some(q=>q.id===state.selected))state.selected=state.list.quests[0]?.id||null;
    renderList();saveURL();$('quest-refreshed').textContent='Last successful refresh: '+new Date(state.list.refreshed_at).toLocaleString();
    if(state.selected)loadDetail();else clearDetail('No quest selected. Try another search or view.');
  }catch(e) {if(request===state.listRequest&&key===context()) {error((e.name==='AbortError'?'Quest list request timed out.':e.message)+(state.list?' Showing the previous successful list.':''));if(!state.list)$('quest-list').replaceChildren(node('p','Quest data unavailable. Use Refresh Now to retry.','quest-list-empty'));}}
  finally {clearTimeout(timeout);if(request===state.listRequest){$('quest-refresh').disabled=false;$('quest-list').setAttribute('aria-busy','false');if(state.list){$('quest-prev').disabled=state.page===0;$('quest-next').disabled=(state.page+1)*state.list.page_size>=state.list.total;}}}
}
function openCharacter(name) {
  if(!/^[A-Za-z]{2,12}$/.test(name))return;
  state.name=name[0].toUpperCase()+name.slice(1).toLowerCase();state.page=0;state.selected=null;loadList(true);
}
$('quest-character-form').addEventListener('submit',e=>{e.preventDefault();openCharacter($('quest-character').value.trim());});
$('quest-refresh').addEventListener('click',()=>refreshGroups());
$('quest-search-form').addEventListener('submit',e=>{e.preventDefault();state.search=$('quest-search').value.trim();state.page=0;state.selected=null;loadList(true);});
$('quest-class').addEventListener('change',()=>{state.classId=Number($('quest-class').value);state.search=$('quest-search').value.trim();state.page=0;state.selected=null;loadList(true);});
$('quest-search-clear').addEventListener('click',()=>{state.search='';state.page=0;state.selected=null;loadList(true);});
for(const mode of ['active','completed','all']) {
  const tab=$('mode-'+mode);
  tab.addEventListener('click',()=>{if(mode===state.mode)return;state.mode=mode;state.page=0;state.search='';state.selected=null;loadList(true);});
  tab.addEventListener('keydown',e=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();
    const tabs=[...document.querySelectorAll('.quest-mode-tabs button')],i=tabs.indexOf(tab);
    const next=e.key==='Home'?0:e.key==='End'?2:(i+(e.key==='ArrowRight'?1:-1)+3)%3;tabs[next].click();tabs[next].focus();
  });
}
$('quest-prev').addEventListener('click',()=>{if(state.page>0){--state.page;state.selected=null;loadList(true);}});
$('quest-next').addEventListener('click',()=>{++state.page;state.selected=null;loadList(true);});
let nameTimer;
$('quest-character').addEventListener('input',()=>{
  clearTimeout(nameTimer);const term=$('quest-character').value.trim();if(!/^[A-Za-z]{0,12}$/.test(term))return;
  nameTimer=setTimeout(async()=>{try{const response=await fetch('/api/characters?q='+encodeURIComponent(term));const data=await response.json();
    if($('quest-character').value.trim()!==term)return;
    $('quest-character-options').replaceChildren(...(data.characters||[]).map(row=>{const n=node('option');n.value=row[0];return n;}));
  }catch{/* Names can be entered without suggestions. */}},250);
});
function selectedGroup() {
  return groupConfig?.groups.find(group=>group.id===groupConfig.selected);
}
function selectedRoster() {
  return watchView?{id:'playerbot-watch',name:'Playerbot Watch',members:watchedNames}:selectedGroup();
}
function rosterStatus() {
  return watchView?(watchedNames.length?'All watched playerbots · No group membership required.':'No playerbots watched. Add them on the Dashboard.')
    :selectedGroup()?'Shared with the Dashboard, Armory and Professions.':'Create your first group on the Dashboard, choose Playerbot Watch, or enter a character below.';
}
function renderGroupControls() {
  const select=$('quest-group'),groups=groupConfig?.groups||[];
  select.replaceChildren();
  if(!groupConfig) {
    select.append(node('option','Groups unavailable'));select.disabled=true;
  } else {
    if(!groups.length){const empty=node('option','No saved groups');empty.value='';empty.disabled=true;select.append(empty);}
    for(const group of groups) {const option=node('option',group.name+' ('+group.members.length+')');option.value=group.id;select.append(option);}
    const watch=node('option','Playerbot Watch ('+watchedNames.length+')');watch.value='__watch__';select.append(watch);
    select.value=watchView?'__watch__':groupConfig.selected||'';select.disabled=groupBusy;
  }
  $('quest-shortcuts').replaceChildren();
  const names=selectedRoster()?.members||[];
  for(const name of names) {
    const button=node('button',name);button.type='button';
    button.classList.toggle('active',name.toLowerCase()===state.name.toLowerCase());
    button.addEventListener('click',()=>openCharacter(name));$('quest-shortcuts').append(button);
  }
}
function useGroupCharacter() {
  const members=selectedRoster()?.members||[];
  state.name=members.find(name=>name.toLowerCase()===state.name.toLowerCase())||members[0]||'';
  state.page=0;state.selected=null;
}
async function readGroupSession(initial=false) {
  const response=await fetch('/api/session',{cache:'no-store'});
  if(!response.ok)throw new Error('Cannot load saved groups.');
  const session=await response.json();
  const previous=JSON.stringify(selectedRoster());
  groupConfig=session.groups;groupToken=session.token;watchedNames=session.bots||[];
  const changed=previous!==JSON.stringify(selectedRoster());
  if(initial) {if(!state.name)state.name=selectedRoster()?.members[0]||'';}
  else if(changed)useGroupCharacter();
  renderGroupControls();
  $('quest-group-status').textContent=rosterStatus();
  return changed;
}
async function refreshGroups() {
  if(groupBusy)return;
  groupBusy=true;$('quest-group').disabled=true;$('quest-refresh').disabled=true;
  let changed=false;
  try {changed=await readGroupSession();}
  catch(e) {$('quest-group-status').textContent=e.message+' Use Refresh Now to retry.';}
  try {await loadList(changed);}
  finally {groupBusy=false;renderGroupControls();$('quest-refresh').disabled=false;}
}
$('quest-group').addEventListener('change',async()=>{
  if(groupBusy||!groupConfig)return;
  const id=$('quest-group').value;
  groupBusy=true;$('quest-group').disabled=true;$('quest-refresh').disabled=true;
  $('quest-group-status').textContent='Saving group selection…';
  try {
    if(id==='__watch__') {
      watchView=true;useGroupCharacter();renderGroupControls();$('quest-group-status').textContent=rosterStatus();
      await loadList(true);return;
    }
    const response=await fetch('/api/groups',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':groupToken},body:JSON.stringify({action:'select',id})});
    const payload=await response.json();
    if(!response.ok||!payload.ok)throw new Error(payload.error||'Cannot select group.');
    groupConfig=payload.groups;watchView=false;useGroupCharacter();renderGroupControls();
    $('quest-group-status').textContent='Group selection saved for all pages.';
    await loadList(true);
  } catch(e) {
    $('quest-group-status').textContent='Group selection was not changed. '+e.message;
  } finally {groupBusy=false;renderGroupControls();$('quest-refresh').disabled=false;}
});
// A page restored by browser Back/Forward must pick up the latest shared selection.
window.addEventListener('pageshow',event=>{if(event.persisted)refreshGroups();});
async function init() {
  try {await readGroupSession(true);}
  catch(e) {renderGroupControls();$('quest-group-status').textContent=e.message+' Use Refresh Now to retry.';}
  loadList(true);
}
init();
