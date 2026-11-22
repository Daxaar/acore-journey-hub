(()=>{'use strict';
const $=id=>document.getElementById(id),el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
const labels={human:'Human',alt_bot:'Alt-bot',random_bot:'Random bot',unknown_bot:'Unknown bot'};
let token='',busy=false,initialized=false,selected=null,selectedGuid=Number(new URLSearchParams(location.search).get('guid'))||null,last=null,filters=new URLSearchParams();
const initial=new URLSearchParams(location.search);if(initial.has('map')&&initial.has('zone'))selected=[initial.get('map'),initial.get('zone')];
async function request(url,options){const response=await fetch(url,{cache:'no-store',...options}),data=await response.json();if(!response.ok||data.ok===false)throw Error(data.error||'Live World unavailable');return data;}
function error(message){$('world-error').textContent=message;$('world-error').hidden=!message;}
function cell(row,text){const c=el('td',text);row.append(c);return c;}
function activate(row,callback){row.tabIndex=0;row.addEventListener('click',callback);row.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();callback();}});}
function detail(){
 const panel=$('character-detail'),c=last?.characters.find(c=>c.guid===selectedGuid);
 if(!c){panel.replaceChildren();delete panel.dataset.guid;return;}
 if(panel.dataset.guid===String(c.guid))return;
 panel.dataset.guid=String(c.guid);panel.replaceChildren();
 const heading=el('div');heading.className='world-armory-heading';const title=el('h3',c.name+' · Armory');title.className='world-name class-'+c.class;
 const link=el('a','Open full Armory ↗');link.href='/armory?name='+encodeURIComponent(c.name);link.target='_blank';link.rel='noopener';heading.append(title,link);
 const frame=el('iframe');frame.className='world-armory-frame';frame.title=c.name+' — character model and equipment';frame.src='/armory-embed?name='+encodeURIComponent(c.name);
 panel.append(heading,el('p','Saved equipment and appearance · inventory updates on character saves, independently of live positions.'),frame);
}
function xpRate(character) {
 return Number.isInteger(character.observed_xp_gained) && character.xp_observed_seconds >= 60 && !character.xp_partial
  ? Math.round(character.observed_xp_gained * 3600 / character.xp_observed_seconds) : null;
}

function characterState(character) {
 return !character.alive ? 'Dead' : character.in_combat ? 'Combat' : character.moving ? 'Moving' : 'Idle';
}

const zoneSort = {key:'bots', direction:-1};
const characterSort = {key:'name', direction:1};
const collator = new Intl.Collator(undefined, {numeric:true, sensitivity:'base'});
const characterValues = {
 name: row => row.name,
 type: row => labels[row.bot_type] || row.bot_type,
 level: row => row.level + Math.min(0.999, (row.xp || 0) / (row.next_level_xp || 1)),
 area: row => row.area_name || row.zone_name,
 rate: xpRate,
 state: characterState,
 age: row => row.session_age_seconds,
};

function sortedRows(rows, sort, value) {
 return [...rows].sort((left, right) => {
  const a = value(left, sort.key), b = value(right, sort.key);
  if (a == null && b != null) return 1;
  if (b == null && a != null) return -1;
  const order = a == null ? 0 : typeof a === 'number' ? a-b : collator.compare(a,b);
  return sort.direction * order || collator.compare(left.name,right.name);
 });
}

function bindSort(listId, sort, numericKeys, renderRows) {
 const buttons = [...$(listId).closest('table').querySelectorAll('.world-sort')];
 function indicators() {
  for (const button of buttons) {
   const active = button.dataset.sort === sort.key;
   button.closest('th').setAttribute('aria-sort', active ? (sort.direction === 1 ? 'ascending' : 'descending') : 'none');
  }
 }
 for (const button of buttons) button.addEventListener('click', () => {
  const key = button.dataset.sort;
  sort.direction = key === sort.key ? -sort.direction : numericKeys.includes(key) ? -1 : 1;
  sort.key = key;
  indicators();
  if (last) renderRows(last);
 });
 indicators();
}

function characters(data){const body=$('character-list'),wanted=new Set();let position=0;for(const c of sortedRows(data.characters, characterSort, (row,key)=>characterValues[key](row))){const key=String(c.guid);wanted.add(key);let row=body.querySelector('[data-guid="'+key+'"]');if(!row){row=el('tr');row.dataset.guid=key;for(let i=0;i<7;i++)cell(row,'');activate(row,()=>{selectedGuid=c.guid;for(const item of body.children)item.setAttribute('aria-selected',String(item.dataset.guid===String(c.guid)));detail();$('character-detail').scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});});}if(body.children[position]!==row)body.insertBefore(row,body.children[position]||null);position++;row.setAttribute('aria-selected',String(c.guid===selectedGuid));const cells=row.children;
cells[0].replaceChildren();if(c.faction==='Alliance'||c.faction==='Horde'){const icon=el('img');icon.src='/faction-'+c.faction.toLowerCase()+'.png';icon.alt=c.faction;icon.title=c.faction;icon.width=24;icon.height=24;icon.className='world-faction-icon';icon.addEventListener('error',()=>{icon.hidden=true;},{once:true});cells[0].append(icon);}cells[0].append(document.createTextNode(c.name));cells[0].className='world-name class-'+c.class;cells[0].title=c.race_name+' '+c.class_name+' · '+c.faction;
cells[1].textContent=labels[c.bot_type]||c.bot_type;const pct=c.next_level_xp?Math.min(100,100*c.xp/c.next_level_xp):100;cells[2].replaceChildren(document.createTextNode(c.level+' · '+pct.toFixed(1)+'%'));const progress=el('progress');progress.max=100;progress.value=pct;progress.className='world-xp';cells[2].append(progress);
if (Number.isInteger(c.observed_xp_gained)) {
 const xp = el('small', (c.xp_partial ? '≥' : '+')+c.observed_xp_gained.toLocaleString()+' XP observed');
 xp.className = 'world-session-xp';
 const minutes = Math.floor(c.xp_observed_seconds/60);
 xp.title = 'Since first seen by the Hub this session ('+minutes+' min ago)'+(c.xp_partial?' · some XP could not be reconstructed':'');
 cells[2].append(xp);
}
cells[3].textContent=c.area_name||c.zone_name;const rate = xpRate(c);
cells[4].textContent = rate === null ? '—' : rate.toLocaleString();
cells[4].title = rate !== null ? 'Average since first seen by the Hub' : c.xp_partial ? 'Some XP could not be reconstructed' : 'Available after one minute of observed XP';
cells[4].className='world-coords';
cells[5].textContent=characterState(c);cells[6].textContent=Math.floor(c.session_age_seconds/3600)+'h '+Math.floor(c.session_age_seconds%3600/60)+'m';}
for(const row of [...body.children])if(!wanted.has(row.dataset.guid))row.remove();detail();}
let reloadForSelection = false;
function refreshSelection() {
 if (busy) reloadForSelection = true;
 else load();
}
function chooseZone(map, zone) {
 selected = map === undefined ? null : [map, zone];
 selectedGuid = null;
 scrollToArmory = false;
 refreshSelection();
}
let scrollToArmory = false;
function chooseMapCharacter(character) {
 selected = [character.map_id, character.zone_id];
 selectedGuid = character.guid;
 scrollToArmory = true;
 refreshSelection();
}
function renderZones(data){$('zone-list').replaceChildren();for(const zone of sortedRows(data.zones, zoneSort, (row,key)=>row[key])){const row=el('tr');row.dataset.zone=zone.zone_id;row.setAttribute('aria-selected',String(selected&&String(zone.map_id)===String(selected[0])&&String(zone.zone_id)===String(selected[1])));cell(row,zone.name+' · '+zone.map_name);cell(row,zone.bots);cell(row,zone.human);cell(row,zone.total);row.title=zone.random_bot+' random, '+zone.alt_bot+' alt, '+zone.unknown_bot+' unknown';activate(row,()=>{chooseZone(zone.map_id,zone.zone_id);});$('zone-list').append(row);}}
bindSort("zone-list", zoneSort, ["bots","human","total"], renderZones);
bindSort("character-list", characterSort, ["level","rate","age"], characters);
function render(data){last=data;if(!initialized){$('capture').checked=data.control.enabled;$('interval').value=data.control.interval_ms;$('quests').checked=data.control.include_quests;initialized=true;}
$('capture-form').querySelector('button').disabled=!data.configured;
const age=data.age_ms===null?'':(' · snapshot '+(data.age_ms/1000).toFixed(1)+'s old');$('world-status').textContent={running:'Live capture running',off:'Capture off',starting:'Waiting for exporter',stale:'Snapshot stale — live positions withheld',unconfigured:'Exporter not configured'}[data.state]+age;
$('world-counts').replaceChildren();for(const [key,label] of [['total','Online'],['human','Human players'],['alt_bot','Alt-bots'],['random_bot','Random bots'],['unknown_bot','Unknown bots']]){const card=el('article',label);card.prepend(el('strong',data.counts?.[key]??'—'));$('world-counts').append(card);}
renderZones(data);
const zone=data.zones.find(z=>selected&&String(z.map_id)===String(selected[0])&&String(z.zone_id)===String(selected[1]));$('zone-title').textContent=selected?(zone?.name||'Selected zone'):'Choose a zone';characters(data);
window.LiveWorldMap.render(data, selected, chooseZone, chooseMapCharacter);
if (scrollToArmory && $('character-detail').dataset.guid === String(selectedGuid)) {
 scrollToArmory = false;
 $('character-detail').scrollIntoView({block:'start'});
}
$('level-summary').textContent=data.levels.map(l=>'Level '+l.range+': '+l.count).join(' · ');
const m=data.metadata;$('world-metrics').textContent=data.state==='running'?'Capture '+Number(m.capture_ms).toFixed(2)+' ms · JSON '+Number(m.serialize_ms).toFixed(2)+' ms · previous write '+Number(m.previous_write_ms).toFixed(2)+' ms · '+(data.file_size_bytes/1024).toFixed(0)+' KiB · skipped snapshots '+m.dropped_snapshots+' · updated '+new Date(m.generated_at_ms).toLocaleTimeString():'';}
async function load(){if(busy)return;busy=true;try{const params=new URLSearchParams(filters);params.set('positions','1');if(selected){params.set('map',selected[0]);params.set('zone',selected[1]);}const data=await request('/api/live-world?'+params);if (!reloadForSelection) render(data.result);error('');}catch(e){error(e.message);}finally{busy=false;if(reloadForSelection){reloadForSelection=false;load();}}}
let guildOptions = [];
function updateGuildOptions() {
  const dropdown = $('guild');
  const current = dropdown.value;
  const faction = $('faction').value;
  const suffix = {Alliance: ' (A)', Horde: ' (H)'};
  const visible = guildOptions.filter(guild => !faction || guild.faction === faction);
  dropdown.replaceChildren(new Option('All guilds', ''), ...visible.map(guild =>
    new Option(guild.name + (suffix[guild.faction] || ''), guild.id)));
  if (visible.some(guild => String(guild.id) === current)) dropdown.value = current;
}

request('/api/live-world/guilds').then(({guilds}) => {
  guildOptions = guilds;
  updateGuildOptions();
}).catch(err => {
  $('guild').options[0].textContent = err.message;
  $('guild').disabled = true;
});
const filterForm = $('filter-form');
function applyFilters() {
  const next = new URLSearchParams();
  for (const key of ['type', 'faction', 'guild']) {
    if ($(key).value) next.set(key, $(key).value);
  }
  for (const [key, fallback] of [['min', '1'], ['max', '80']]) {
    const value = $(key).value;
    if (value && value !== fallback) next.set(key, value);
  }
  const query = $('search').value.trim();
  if (query) next.set('q', query);
  if (next.toString() === filters.toString()) return;
  filters = next;
  refreshSelection();
}

filterForm.addEventListener('submit', event => {
  event.preventDefault();
  applyFilters();
});
filterForm.addEventListener('change', event => {
  if (event.target.id === 'faction' && !$('guild').disabled) updateGuildOptions();
  if (event.target.matches('select')) applyFilters();
});
filterForm.addEventListener('focusout', event => {
  if (event.target.matches('input')) applyFilters();
});
filterForm.addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.isComposing || !event.target.matches('input')) return;
  event.preventDefault();
  applyFilters();
});
$('capture-form').addEventListener('submit',async e=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{if(!token)token=(await request('/api/session')).token;await request('/api/live-world/control',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':token},body:JSON.stringify({enabled:$('capture').checked,interval_ms:Number($('interval').value),include_quests:$('quests').checked})});await load();}catch(e){error(e.message);}finally{button.disabled=false;}});
load();setInterval(()=>{if(!document.hidden)load();},5000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
})();