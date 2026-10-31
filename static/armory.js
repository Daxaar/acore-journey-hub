'use strict';
const inventoryPage = location.pathname === '/inventory';
const $ = id => document.getElementById(id);
const races = {1:'Human',2:'Orc',3:'Dwarf',4:'Night Elf',5:'Undead',6:'Tauren',7:'Gnome',8:'Troll',10:'Blood Elf',11:'Draenei'};
const classes = {1:'Warrior',2:'Paladin',3:'Hunter',4:'Rogue',5:'Priest',6:'Death Knight',7:'Shaman',8:'Mage',9:'Warlock',11:'Druid'};
const stats = {0:'Mana',1:'Health',3:'Agility',4:'Strength',5:'Intellect',6:'Spirit',7:'Stamina',12:'Defense rating',13:'Dodge rating',14:'Parry rating',15:'Block rating',16:'Melee hit rating',17:'Ranged hit rating',18:'Spell hit rating',19:'Melee critical strike rating',20:'Ranged critical strike rating',21:'Spell critical strike rating',31:'Hit rating',32:'Critical strike rating',35:'Resilience rating',36:'Haste rating',38:'Attack power',39:'Ranged attack power',43:'Mana per 5 sec',44:'Armor penetration rating',45:'Spell power',46:'Health per 5 sec',47:'Spell penetration',48:'Block value'};
let currentName = new URLSearchParams(location.search).get('name') || '';
if (!/^[A-Za-z]{2,12}$/.test(currentName)) currentName = '';
let groupConfig = null, groupToken = null, groupBusy = false, spaceRequest = 0;
let storage = 'bags';
let characterTab = 'character', skillsRequest = 0, skillsController = null, armorySkillsName = null;
let data = null, busy = false, timer = null, selectedItem = null;
function node(tag, text, cls) { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; }
function quality(item) { const q = Number(item?.Quality); return Number.isInteger(q) && q >= 0 && q <= 7 ? q : 1; }
function icon(item, index) {
  const n = node('span', null, `item-icon ${item ? 'quality-' + quality(item) : 'empty'}`);
  if (item) {
    const img = node('img'); img.alt = ''; img.width = 56; img.height = 56;
    img.src = item.icon ? `/icons/${encodeURIComponent(item.icon)}.jpg` : '/item-placeholder.svg';
    img.addEventListener('error', () => { if (!img.src.endsWith('/item-placeholder.svg')) img.src = '/item-placeholder.svg'; });
    n.append(img);
    if (item.count > 1) n.append(node('span', item.count, 'stack-count'));
  } else n.append(node('span', index == null ? '·' : index, 'empty-index'));
  return n;
}
function inspect(item, label, key) {
  selectedItem = key;
  document.querySelectorAll('[data-item-key]').forEach(n => n.classList.toggle('item-selected', n.dataset.itemKey === key));
  renderItem($('item-detail'), item, label);
}
function renderItem(detail, item, label, tooltip = false) {
  if(tooltip&&item){ItemTooltip.render(detail,{...item,id:item.entry,quality:item.Quality,level:item.ItemLevel,required_level:item.RequiredLevel});return;}
  detail.replaceChildren();
  if (!item) { const title = node('h2', 'Empty slot'); if (!tooltip) title.id = 'item-title'; detail.append(title, node('p', label)); return; }
  detail.append(icon(item));
  const title = node('h2', null, 'quality-text-' + quality(item)); if (tooltip) title.textContent = item.name; else title.append(wowheadLink(item.name,'item',item.entry)); if (!tooltip) title.id = 'item-title'; detail.append(title);
  detail.append(node('p', label, 'item-note'));
  const line = (text, cls) => detail.append(node('p', text, cls));
  line(`Item level ${item.ItemLevel ?? 'unknown'} · Requires level ${item.RequiredLevel ?? 'unknown'}`, 'item-note');
  if (item.armor) line(`${item.armor} base armor`);
  if (item.dmg_max1) {
    line(`${item.dmg_min1}–${item.dmg_max1} base damage`);
    if (item.delay) line(`Speed ${(item.delay / 1000).toFixed(2)} · ${((item.dmg_min1 + item.dmg_max1) * 500 / item.delay).toFixed(1)} base DPS`);
  }
  for (let i = 1; i <= 10; i++) if (item['stat_value' + i]) line(`+${item['stat_value' + i]} ${stats[item['stat_type' + i]] || 'Stat #' + item['stat_type' + i]}`, 'item-stat');
  for (const enchant of item.enchant_labels) line(enchant, 'item-stat');
  if (item.randomPropertyId) line('Random property/enchantment values are shown as saved; scaled totals are not calculated.', 'item-note');
  if (item.ContainerSlots) line(`${item.ContainerSlots}-slot bag`);
  if (item.MaxDurability) line(`Durability ${item.durability ?? '?'} / ${item.MaxDurability}`);
  if (item.count > 1) line(`Stack: ${item.count}`);
  if (item.description) line(item.description);
  detail.append(node('hr'));
  line(`Item #${item.entry ?? '?'} · Display #${item.displayid ?? '?'}`, 'item-note');
  line('Saved instance details. Hover for server effects and requirements; final combat totals are not simulated.', 'item-note');
}
function slotButton(item, label, key, equipment = false, index = null) {
  const b = node('button', null, equipment ? 'equipment-slot' : 'bag-cell'); b.type = 'button';
  b.dataset.itemKey = key; b.classList.toggle('item-selected', selectedItem === key);
  b.setAttribute('aria-label', `${label}: ${item ? item.name + (item.count > 1 ? ' ×' + item.count : '') : 'Empty'}`); b.append(icon(item, index));
  if (equipment) { const copy = node('span', null, 'slot-copy'); copy.append(node('span', label, 'slot-label'), node('span', item?.name || 'Empty', 'slot-name')); b.append(copy); }
  b.addEventListener('click', () => inspect(item, label, key));
  if (item) {
    b.addEventListener('mouseenter', () => showTooltip(b, item, label));
    b.addEventListener('focus', () => showTooltip(b, item, label));
    b.addEventListener('mouseleave', scheduleTooltipHide);
    b.addEventListener('blur', scheduleTooltipHide);
    b.dataset.searchText = `${item.name} ${item.entry ?? ''} ${item.description || ''}`.toLocaleLowerCase();
  }
  return b;
}
let tooltipAnchor = null, tooltipTimer;
function hideTooltip() {
  clearTimeout(tooltipTimer);
  tooltipAnchor?.removeAttribute('aria-describedby');
  tooltipAnchor = null;
  $('item-tooltip').hidden = true;
}
function scheduleTooltipHide() {
  clearTimeout(tooltipTimer);
  tooltipTimer = setTimeout(() => {
    if (!$('item-tooltip').matches(':hover') && tooltipAnchor !== document.activeElement) hideTooltip();
  }, 120);
}
function showTooltip(anchor, item, label) {
  hideTooltip();
  tooltipAnchor = anchor;
  const tip = $('item-tooltip');
  renderItem(tip, item, label, true);
  tip.hidden = false;
  anchor.setAttribute('aria-describedby', 'item-tooltip');
  positionTooltip();
}
function positionTooltip() {
  if (!tooltipAnchor) return;
  const tip = $('item-tooltip');
  const rect = tooltipAnchor.getBoundingClientRect();
  if (rect.bottom < 0 || rect.top > innerHeight) { hideTooltip(); return; }
  ItemTooltip.position(tip,tooltipAnchor);
}
$('item-tooltip').addEventListener('item-tooltip-updated',positionTooltip);
$('item-tooltip').addEventListener('mouseenter', () => clearTimeout(tooltipTimer));
$('item-tooltip').addEventListener('mouseleave', () => {
  if (tooltipAnchor !== document.activeElement) hideTooltip();
});
document.addEventListener('keydown', event => { if (event.key === 'Escape') hideTooltip(); });
window.addEventListener('resize', hideTooltip);
window.addEventListener('scroll', event => { if (!$('item-tooltip').contains(event.target)) positionTooltip(); }, true);
function filterBags() {
  const terms = $('bag-search').value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  let matches = 0;
  document.querySelectorAll('.bag-cell').forEach(button => {
    const filled = button.dataset.searchText !== undefined;
    const match = filled && terms.every(term => button.dataset.searchText.includes(term));
    button.classList.toggle('search-dimmed', terms.length > 0 && !match);
    if (match) matches++;
  });
  $('bag-search-status').textContent = terms.length ? `${matches} matching occupied ${matches === 1 ? 'slot' : 'slots'} · All bags shown` : 'All bags shown · Search by item name, description or ID';
  $('bag-search-clear').disabled = terms.length === 0;
}
$('bag-search')?.addEventListener('input', filterBags);
$('bag-search-clear')?.addEventListener('click', () => { $('bag-search').value = ''; filterBags(); $('bag-search').focus(); });
function activeBags() { return storage === 'bank' ? data.bank : storage === 'guild' ? data.guild_bags : data.bags; }
function renderStorage() {
  if (storage === 'guild' && !data.guild) storage = 'bags';
  $('tab-guild').hidden = !data.guild;
  for (const name of ['bags', 'bank', 'guild']) {
    const tab = $('tab-' + name), active = storage === name;
    tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
  }
  $('bags').setAttribute('aria-labelledby', 'tab-' + storage);
  $('bags-title').textContent = storage === 'bags' ? 'Your bags' : storage === 'bank' ? 'Your bank' : `${data.guild.name} · Guild bank`;
  const bags = activeBags(), capacity = bags.reduce((n,b) => n + b.capacity, 0), occupied = bags.reduce((n,b) => n + b.occupied, 0);
  const money = (storage === 'bags' ? data.character.money : storage === 'guild' ? data.guild.money : 0) || 0;
  $('bag-summary').textContent = `${occupied}/${capacity} slots used · ${capacity - occupied} free` + (storage === 'bank' ? '' : ` · ${Math.floor(money/10000)}g ${Math.floor(money/100)%100}s ${money%100}c`);
  $('storage-note').textContent = storage === 'bags' ? 'Saved carried inventory. Keyring, currency and buyback records are excluded.' : storage === 'bank' ? 'Saved personal bank: 28 bank slots and seven bank bag positions. Empty bag positions may be unpurchased.' : 'Saved guild bank · view only. This local database view shows all purchased tabs; in-game rank permissions are not applied.';
  renderBags();
}
for (const name of ['bags', 'bank', 'guild']) {
  const tab = $('tab-' + name);
  tab?.addEventListener('click', () => {
    storage = name; selectedItem = null; hideTooltip();
    $('item-detail').replaceChildren(node('h2', 'A closer look'), node('p', 'Select an item to inspect it.'));
    renderStorage();
  });
  tab?.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...document.querySelectorAll('.storage-tabs [role="tab"]')].filter(t => !t.hidden);
    const index = tabs.indexOf(tab);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[next].click(); tabs[next].focus();
  });
}
function renderBags() {
  $('bags').replaceChildren();
  activeBags().forEach((bag, bagIndex) => {
    const frame = node('section', null, 'bag-frame'); frame.dataset.bag = bag.id;
    const header = node('header', null, 'bag-header'), copy = node('div');
    if (bag.item) {
      const bagButton = slotButton(bag.item, `${storage === 'bank' ? 'Bank bag' : 'Equipped bag'} ${bagIndex}`, `bagitem:${bag.id}`);
      bagButton.className = 'bag-inspect'; header.append(bagButton);
    } else header.append(icon(bagIndex ? null : {icon:'inv_misc_bag_08',Quality:1}));
    copy.append(node('h3', bag.name), node('p', `${storage === 'guild' ? 'Guild bank tab' : bagIndex ? (storage === 'bank' ? 'Bank bag ' : 'Equipped bag ') + bagIndex : storage === 'bank' ? 'Bank storage' : 'Main inventory'} · ${bag.occupied}/${bag.capacity} slots`));
    header.append(copy); frame.append(header);
    if (bag.capacity) {
      const grid = node('div', null, 'bag-lining');
      bag.slots.forEach((item,i) => grid.append(slotButton(item, `${bag.name} · slot ${i + 1}`, `${bag.id}:${i}`, false, i + 1)));
      frame.append(grid, node('p', `${bag.capacity - bag.occupied} empty slots`, 'bag-footer'));
    } else frame.append(node('p', 'No bag equipped in this slot.', 'bag-empty-message'));
    $('bags').append(frame);
  });
  if (!activeBags().length) $('bags').append(node('p', 'This guild has no purchased bank tabs.', 'empty-state'));
  filterBags();
}
function render() {
  const focusedKey = document.activeElement?.dataset.itemKey;
  hideTooltip();
  const changes = data.changes;
  $('change-status').textContent = changes?.last_observed_change_at ? 'Last observed data change: ' + new Date(changes.last_observed_change_at).toLocaleString() : 'Last observed data change: none since monitoring began for this character';
  $('change-status').title = 'Compared with the previous successful inventory snapshot in this dashboard process; not a server save timestamp.';
  const c = data.character;
  $('inventory').hidden = false; $('character-title').textContent = c.name;
  $('character-subtitle').textContent = `Level ${c.level} ${races[c.race] || 'Race #' + c.race} ${classes[c.class] || 'Class #' + c.class}`;
  $('character-quest-log').href = '/quest-log?name=' + encodeURIComponent(c.name);
  if (!inventoryPage) {
    window.JourneyHubModel?.update(c,data.equipment);
    $('equipped-count').textContent = `${data.equipment.filter(e => e.item).length}/19 equipped`;
    $('appearance').textContent = `Race ${c.race} · Gender ${c.gender} · Skin ${c.skin} · Face ${c.face} · Hair style ${c.hairStyle} · Hair colour ${c.hairColor} · Facial style ${c.facialStyle}. These saved IDs select the optional equipped client model; the paper-doll is the fallback.`;
    for (const [id, slots] of [['equipment-left',[0,1,2,14,4,3,18,8]],['equipment-right',[9,5,6,7,10,11,12,13]],['equipment-weapons',[15,16,17]]]) {
      $(id).replaceChildren(...slots.map(i => { const e = data.equipment[i]; return slotButton(e.item, e.label, `equipment:${i}`, true); }));
    }

  }
  $('warnings').textContent = data.warnings.join(' ');
  if (inventoryPage) renderStorage();
  if (characterTab === 'skills') loadArmorySkills(true);
  // Keep the inspected item current after a refresh, including removed items.
  if (selectedItem) {
    const [key, value] = selectedItem.split(':');
    if (key === 'equipment') { const e = data.equipment[Number(value)]; if (e) inspect(e.item, e.label, selectedItem); }
    else if (key === 'bagitem') { const bag = activeBags().find(b => b.id === value); if (bag) inspect(bag.item, 'Equipped bag', selectedItem); }
    else { const bag = activeBags().find(b => b.id === key); if (bag) inspect(bag.slots[Number(value)], `${bag.name} · slot ${Number(value)+1}`, selectedItem); }
  }
  if (focusedKey) [...document.querySelectorAll('[data-item-key]')].find(b => b.dataset.itemKey === focusedKey)?.focus({preventScroll:true});
  document.querySelectorAll('#shortcuts button').forEach(n => n.classList.toggle('active', n.dataset.character.toLowerCase() === c.name.toLowerCase()));
}
async function refresh() {
  if(!currentName){$('refresh-status').textContent='Enter a character name or create a group on the Dashboard.';return;}
  if (busy || groupBusy) return; busy = true; $('refresh').disabled = true; $('armory-group').disabled = true;
  let refreshedInventory = null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch('/api/armory?name=' + encodeURIComponent(currentName), {cache:'no-store', signal:controller.signal});
    const result = await response.json(); if (!response.ok || !result.ok) throw new Error(result.error || 'Inventory unavailable');
    data = result.inventory; render(); $('error').hidden = true;
    refreshedInventory = data;
    $('refresh-status').textContent = 'Last successful refresh: ' + new Date(data.refreshed_at).toLocaleTimeString();
  } catch (error) {
    $('error').textContent = error.message + (data ? ' Showing the last successful saved snapshot.' : ''); $('error').hidden = false;
  } finally { clearTimeout(timeout); busy = false; $('refresh').disabled = false; $('armory-group').disabled = !groupConfig || groupBusy; refreshBagSpace(refreshedInventory); }
}
function openCharacter(name) {
  if (busy || groupBusy || !/^[A-Za-z]{2,12}$/.test(name)) return;
  if (name.toLowerCase() !== currentName.toLowerCase()) {
    ++skillsRequest; skillsController?.abort(); armorySkillsName = null;
    $('armory-skills')?.replaceChildren(); if ($('armory-skills-status')) $('armory-skills-status').textContent = '';
    data = null; storage = 'bags'; selectedItem = null; hideTooltip(); window.JourneyHubModel?.clear(); $('inventory').hidden = true;
    $('item-detail').replaceChildren(node('h2','A closer look'), node('p','Select an item to inspect it.'));
    $('refresh-status').textContent = 'Waiting for saved inventory';
    $('change-status').textContent = '';
  }
  currentName = name; $('character-name').value = name; history.replaceState(null, '', location.pathname + '?name=' + encodeURIComponent(name)); syncCharacterLinks(); refresh();
}
$('character-name').value = currentName;
$('character-form').addEventListener('submit', event => { event.preventDefault(); openCharacter($('character-name').value.trim()); });
$('refresh').addEventListener('click', refresh);
function schedule() { clearInterval(timer); const seconds = Number($('interval').value); if (seconds) timer = setInterval(() => { if (!document.hidden) refresh(); }, seconds * 1000); }
$('interval').addEventListener('change', schedule);
let searchTimer;
$('character-name').addEventListener('input', () => {
  clearTimeout(searchTimer); const q = $('character-name').value;
  if (!/^[A-Za-z]{0,12}$/.test(q)) return;
  searchTimer = setTimeout(async () => {
    try { const response = await fetch('/api/characters?q=' + encodeURIComponent(q)); const result = await response.json();
      if (q !== $('character-name').value || !result.ok) return;
      $('character-options').replaceChildren(...result.characters.map(c => { const n = node('option'); n.value = c[0]; return n; }));
    } catch (_) { /* The current inventory remains usable if name search is unavailable. */ }
  }, 250);
});
function selectedGroup() { return groupConfig?.groups.find(g => g.id === groupConfig.selected); }
function setSpace(name, free, note = '') {
  const button = [...$('shortcuts').querySelectorAll('button')].find(b => b.dataset.character.toLowerCase() === name.toLowerCase());
  if (!button) return;
  const pill = button.querySelector('.bag-space-pill');
  pill.textContent = free == null ? '—' : free;
  pill.classList.toggle('unknown', free == null); pill.classList.toggle('full', free === 0);
  pill.title = free == null ? `${name}: bag space unavailable${note ? ' · ' + note : ''}` : `${name}: ${free} free carried-bag slots${note ? ' · ' + note : ''}`;
  pill.setAttribute('aria-label', pill.title);
}
function renderGroup() {
  const group = selectedGroup();
  $('armory-group').replaceChildren(...groupConfig.groups.map(g => {
    const option = node('option', `${g.name} (${g.members.length})`); option.value = g.id; return option;
  }));
  $('armory-group').value = groupConfig.selected;
  $('shortcuts').replaceChildren(...(group?.members||[]).map(name => {
    const button = node('button'); button.type = 'button'; button.dataset.character = name;
    button.setAttribute('aria-label', name);
    const pill = node('span', '—', 'bag-space-pill unknown'); pill.id = 'space-' + name;
    button.setAttribute('aria-describedby', pill.id); pill.setAttribute('aria-label', name + ': bag space loading');
    button.append(node('span',name),pill);button.addEventListener('click', () => openCharacter(name));
    button.classList.toggle('active', name.toLowerCase() === currentName.toLowerCase());
    return button;
  }));
  $('armory-group').disabled=!group;
  $('armory-group-status').textContent = group?'Pills show free carried-bag slots · Saved inventory':'Create a group on the Dashboard, or open a character by name.';
}
async function refreshBagSpace(selectedSnapshot = null) {
  const group = selectedGroup(); if (!group) return;
  const request = ++spaceRequest, groupId = group.id;
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(),15000);
  try {
    const response = await fetch('/api/armory/space?names=' + encodeURIComponent(group.members.join(',')), {cache:'no-store',signal:controller.signal});
    const result = await response.json();
    if (request !== spaceRequest || selectedGroup()?.id !== groupId) return;
    if (!response.ok || !result.ok) throw new Error(result.error || 'Bag space unavailable');
    for (const member of result.space.characters) setSpace(member.name, member.free, member.found ? 'Saved inventory' : 'Character not found');
    // The selected character's full inventory may be newer than the shared summary cache.
    if (selectedSnapshot) setSpace(selectedSnapshot.character.name, selectedSnapshot.capacity - selectedSnapshot.occupied, 'Saved inventory');
    $('armory-group-status').textContent = 'Pills show free carried-bag slots · Saved inventory';
  } catch (_) {
    if (request !== spaceRequest || selectedGroup()?.id !== groupId) return;
    for (const name of group.members) {
      const pill = $('space-' + name);
      if (pill?.textContent !== '—') {
        pill.title = name + ': previous bag-space count · Refresh failed'; pill.setAttribute('aria-label',pill.title);
      } else setSpace(name,null,'Refresh failed');
    }
    $('armory-group-status').textContent = 'Bag-space refresh failed; existing counts are from the previous read.';
  } finally { clearTimeout(timeout); }
}
$('armory-group').addEventListener('change', async () => {
  if (busy || groupBusy) return;
  groupBusy = true; $('armory-group').disabled = true; $('refresh').disabled = true;
  try {
    const response = await fetch('/api/groups', {method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':groupToken},
      body:JSON.stringify({action:'select',id:$('armory-group').value})});
    const result = await response.json(); if (!response.ok || !result.ok) throw new Error(result.error || 'Cannot select group.');
    groupConfig = result.groups; ++spaceRequest; renderGroup();
    const group = selectedGroup();
    const next = group.members.find(n => n.toLowerCase() === currentName.toLowerCase()) || group.members[0];
    groupBusy = false; openCharacter(next);
  } catch (error) {
    $('armory-group').value = groupConfig.selected;
    $('armory-group-status').textContent = error.message || 'Cannot select group.';
  } finally {
    groupBusy = false; $('armory-group').disabled = busy || !groupConfig; $('refresh').disabled = busy;
  }
});
function showCharacterTab(name) {
  characterTab = name;
  $('character-equipment-panel').hidden = name !== 'character'; $('character-skills-panel').hidden = name !== 'skills';
  for (const [id,value] of [['character-tab','character'],['character-skills-tab','skills']]) {
    $(id).setAttribute('aria-selected',String(name === value)); $(id).tabIndex = name === value ? 0 : -1;
  }
  if (name === 'skills') loadArmorySkills();
}
async function loadArmorySkills(force = false) {
  if (!force && armorySkillsName === currentName.toLowerCase()) return;
  const request = ++skillsRequest; skillsController?.abort(); const controller = new AbortController(); skillsController = controller;
  const name = currentName, timeout = setTimeout(() => controller.abort(),15000);
  $('armory-skills-status').textContent = 'Reading saved skills…';
  if (!armorySkillsName) $('armory-skills').replaceChildren(node('p','Opening the Skills pane…','game-empty'));
  try {
    const response = await fetch('/api/skills?names=' + encodeURIComponent(name), {cache:'no-store',signal:controller.signal}); const result = await response.json();
    if (request !== skillsRequest || name !== currentName) return;
    if (!response.ok || !result.ok) throw new Error(result.error || 'Skills unavailable');
    window.JourneyHubSkills.render($('armory-skills'),result.result.characters[0]); armorySkillsName = name.toLowerCase();
    $('armory-skills-status').textContent = 'Last skill refresh: ' + new Date(result.result.refreshed_at).toLocaleString();
  } catch (error) { if (request === skillsRequest) $('armory-skills-status').textContent = (error.name === 'AbortError' ? 'Skill request timed out.' : error.message) + (armorySkillsName ? ' Showing the last successful saved skills.' : ''); }
  finally { clearTimeout(timeout); }
}
$('character-tab')?.addEventListener('click',()=>showCharacterTab('character'));
$('character-skills-tab')?.addEventListener('click',()=>showCharacterTab('skills'));
for (const id of ['character-tab','character-skills-tab']) $(id)?.addEventListener('keydown',event=>{
  if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return; event.preventDefault();
  const skills = event.key === 'End' || (event.key !== 'Home' && id === 'character-tab');
  showCharacterTab(skills ? 'skills' : 'character'); $(skills ? 'character-skills-tab' : 'character-tab').focus();
});
function syncCharacterLinks() {
  document.querySelectorAll('.page-nav a').forEach(link => {
    const url = new URL(link.href);
    if (['/armory','/inventory'].includes(url.pathname)) {
      link.href = url.pathname + (currentName ? '?name=' + encodeURIComponent(currentName) : '');
    }
  });
}
async function init() {
  try {
    const response = await fetch('/api/session', {cache:'no-store'});
    if (!response.ok) throw new Error('Session unavailable');
    const session = await response.json(); groupConfig = session.groups; groupToken = session.token;
    renderGroup();
    const requestedName = new URLSearchParams(location.search).get('name');
    if (!/^[A-Za-z]{2,12}$/.test(requestedName || '')) currentName = selectedGroup()?.members[0]||'';
    $('character-name').value = currentName;
  } catch (_) { $('armory-group-status').textContent = 'Saved groups unavailable. You can still open a character by name.'; }
  syncCharacterLinks(); await refresh(); schedule();
}
init();
