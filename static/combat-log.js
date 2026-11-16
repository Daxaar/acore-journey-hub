const field = (id) => document.getElementById(id);
const format = new Intl.NumberFormat(undefined, {maximumFractionDigits: 1});
let session;
let report;
let reportEvents = [];
let includedEvents = [];
const classes = new Map();
const classStyle = name => 'combat-character class-' + (classes.get(name.toLowerCase()) || 0);
let generation = 0;

const months = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(' ');

function displayDate(year, month, day, clock) {
  const suffix = day >= 11 && day <= 13 ? 'th' : ({1: 'st', 2: 'nd', 3: 'rd'}[day % 10] || 'th');
  return `${day}${suffix} ${months[month - 1]} ${year} ${clock}`;
}

function importDate(value) {
  const [date, clock] = value.split(' ');
  const [year, month, day] = date.split('-').map(Number);
  return displayDate(year, month, day, clock);
}

function clientDate(value) {
  const [date, clock] = value.split(' ');
  const [month, day] = date.split('/').map(Number);
  const [year, savedMonth, savedDay] = report.saved.split(' ')[0].split('-').map(Number);
  const afterImport = month > savedMonth || (month === savedMonth && day > savedDay);
  let inferredYear = year - Number(afterImport);
  // The raw log has no year. Use the most recent matching date at import.
  while (month === 2 && day === 29 && new Date(Date.UTC(inferredYear, 1, 29)).getUTCMonth() !== 1) inferredYear--;
  return displayDate(inferredYear, month, day, clock.split('.')[0]);
}

function node(tag, value) {
  const element = document.createElement(tag);
  if (value !== undefined) element.textContent = value;
  return element;
}

async function request(path, payload) {
  const options = {cache: 'no-store'};
  if (payload) Object.assign(options, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Dashboard-Token': session.token},
    body: JSON.stringify(payload),
  });
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Could not load combat data.');
  return data;
}

function handle(action) {
  return async (event) => {
    event?.preventDefault();
    field('combat-status').textContent = '';
    try { await action(event); }
    catch (error) { field('combat-status').textContent = error.message; }
  };
}

async function list(selected) {
  const {result} = await request('/api/combat-logs');
  const select = field('saved-log');
  select.replaceChildren(new Option('Select a saved log', ''),
    ...result.map(([id, title, date]) => new Option(`${title} · ${importDate(date)} UTC`, id)));
  select.value = selected || '';
  await openLog();
}

async function openLog() {
  const version = ++generation;
  const id = field('saved-log').value;
  field('report').hidden = true;
  field('delete-log').disabled = true;
  field('rename-log').disabled = true;
  if (!id) return;
  const {result} = await request('/api/combat-logs?id=' + encodeURIComponent(id));
  if (version !== generation) return;
  report = result;
  for (const [name, classId] of Object.entries(report.classes || {})) {
    classes.set(name.toLowerCase(), classId);
  }
  const excluded = new Set(report.excluded);
  includedEvents = report.events.filter(event =>
    ![2, 3].some(index => excluded.has(event[index].toLowerCase())));
  field('report-title').textContent = report.title;
  updateSessions();
  selectSession();
  field('report').hidden = false;
  field('delete-log').disabled = false;
  field('rename-log').disabled = false;
  field('boss-only').checked = false;
  field('boss-only').disabled = !report.bosses.length;
  field('boss-summary').textContent = report.bosses.length
    ? 'Recognized Deadmines pulls: ' + report.bosses.map(boss => boss[2]).join(', ')
    : report.dungeon ? 'No supported boss encounters detected. This preview recognizes Deadmines bosses.' : '';
  render();
}

function updateSessions() {
  const threshold = Number(field('combat-gap').value) * 60;
  if (!Number.isFinite(threshold) || threshold < 60 || threshold > 86400) return;
  const timestamps = new Map(report.events.map(event => [event[0], event[14]]));
  const times = [...timestamps.keys()].sort((a, b) => a - b);
  const sessions = [];
  let start = times[0], last = start;
  for (const time of times) {
    if (time - last >= threshold) {
      sessions.push([start, last]);
      start = time;
    }
    last = time;
  }
  sessions.push([start, last]);
  const select = field('combat-session');
  select.replaceChildren(new Option('Entire log', ''),
    ...sessions.filter(([from, to]) => !report.windows.some(window => window[0] === from && window[1] === to))
      .map(([from, to]) => new Option(
        `Session ${sessions.findIndex(window => window[0] === from) + 1} · starts ${clientDate(timestamps.get(from))}`, `${from},${to}`)),
    ...report.windows.map(([from, to, title]) => new Option(title, `${from},${to}`)));
  select.options[0].dataset.end = last;
}

function selectSession() {
  const select = field('combat-session');
  const [start, end] = select.value ? select.value.split(',') : [0, select.options[0].dataset.end];
  field('from').value = start;
  field('to').value = end;
}

function chart(title, rows, key) {
  const section = node('section');
  section.append(node('h3', title));
  const max = rows.reduce((largest, row) => Math.max(largest, row[key]), 1);
  for (const row of [...rows].sort((a, b) => b[key] - a[key])) {
    const label = node(row.select ? 'button' : 'div');
    label.className = 'combat-chart-row';
    const title = node('span', row.name);
    if (row.character) title.className = classStyle(row.character);
    if (row.select) {
      label.type = 'button';
      label.addEventListener('click', row.select);
    }
    if (row.icon) {
      const icon = node('img');
      icon.alt = '';
      icon.width = icon.height = 16;
      icon.src = '/icons/' + row.icon + '.jpg';
      title.prepend(icon);
    }
    label.append(title, document.createTextNode(' · ' + format.format(row[key])));
    const bar = node('progress');
    bar.max = max;
    bar.value = row[key];
    label.append(bar);
    section.append(label);
  }
  return section;
}

function timelineEntry(event) {
  const [time, kind, source, target, spell, amount, spellId, sourceId, targetId,
    , absorbed, power, detail] = event;
  const actor = source || 'An unknown source';
  const self = source && target && sourceId === targetId;
  const recipient = self ? 'themself' : target || 'an unknown target';
  const onTarget = target ? ' on ' + recipient : '';
  const ability = spellId > 0 ? wowheadLink(spell, 'spell', spellId) : spell;
  const value = format.format(amount);
  let parts;

  if (kind === 'ENVIRONMENTAL_DAMAGE') parts = [recipient, ' took ', value, ' damage from ', spell.toLowerCase()];
  else if (kind === 'SWING_DAMAGE') parts = [actor, ' hit ', recipient, ' for ', value, ' melee damage'];
  else if (isDamage(kind)) parts = [actor, ' hit ', recipient, ' with ', ability, ' for ', value, ' damage'];
  else if (kind.endsWith('_HEAL')) parts = [actor, ' healed ', recipient, ' for ', value, ' with ', ability];
  else if (kind === 'SPELL_CAST_START') parts = [actor, ' began casting ', ability, onTarget];
  else if (kind === 'SPELL_CAST_SUCCESS') parts = [actor, ' cast ', ability, onTarget];
  else if (kind === 'SPELL_INTERRUPT') parts = [actor, ' interrupted ', recipient, detail ? ' casting ' + detail : '', ' with ', ability];
  else if (kind === 'SPELL_AURA_APPLIED' || kind === 'SPELL_AURA_REFRESH') {
    const verb = kind === 'SPELL_AURA_APPLIED' ? ' applied ' : ' refreshed ';
    parts = source ? [actor, verb, ability, onTarget] : [recipient, ' gained ', ability];
  } else if (kind === 'SPELL_AURA_REMOVED') parts = [ability, ' faded from ', target || 'an unknown target'];
  else if (kind.startsWith('SPELL_AURA_BROKEN')) parts = [actor, ' broke ', kind === 'SPELL_AURA_BROKEN_SPELL' && detail ? detail : ability, onTarget];
  else if (kind === 'SPELL_DISPEL' || kind === 'SPELL_STOLEN') parts = [actor, kind === 'SPELL_DISPEL' ? ' dispelled ' : ' stole ', detail || 'an effect', ' from ', recipient, ' with ', ability];
  else if (kind === 'SPELL_RESURRECT') parts = [actor, ' resurrected ', recipient, ' with ', ability];
  else if (kind === 'UNIT_DIED' || kind === 'UNIT_DESTROYED') parts = [target || 'An unknown unit', kind === 'UNIT_DIED' ? ' died' : ' was destroyed'];
  else if (kind.endsWith('_ENERGIZE')) {
    const resource = ({0: 'mana', 1: 'rage', 3: 'energy', 6: 'runic power'})[power] || 'power';
    parts = [target || 'An unknown unit', ' gained ', value, ' ', resource, ' from ', ability];
  } else if (kind.endsWith('_MISSED')) {
    parts = absorbed ? [recipient, ' absorbed ', format.format(absorbed), ' damage from ', actor, ' using ', ability]
      : [actor, ' did not land ', ability || 'an attack', onTarget];
  } else parts = [actor, ' triggered ', kind.replaceAll('_', ' ').toLowerCase(), onTarget];

  const item = node('li', time.toFixed(3) + 's · ');
  item.append(...parts, '.');
  return item;
}

function render() {
  if (!report || field('report').hidden) return;
  const start = Number(field('from').value);
  const end = Number(field('to').value);
  if (end < start) throw new Error('The end must be at or after the start.');
  const group = session.groups.groups.find(item => item.id === field('combat-group').value);
  const names = new Set(group?.members.map(name => name.toLowerCase()));
  const totals = new Map();
  const windows = field('boss-only').checked ? report.bosses
    .map(([a,b]) => [Math.max(a,start), Math.min(b,end)]).filter(([a,b]) => a <= b) : [[start,end]];
  const merged = [];
  for (const [a,b] of windows) {
    const last = merged.at(-1);
    if (last && a <= last[1]) last[1] = Math.max(last[1],b);
    else merged.push([a,b]);
  }
  const duration = merged.reduce((sum,[a,b]) => sum+b-a,0);
  reportEvents = includedEvents.filter(([time]) => merged.some(([a,b]) => time >= a && time <= b));
  const first = reportEvents.reduce((earliest, event) =>
    !earliest || event[0] < earliest[0] ? event : earliest, null);
  field('window-start').textContent = first ? 'First recorded event: ' + clientDate(first[14]) + ' (client time, year inferred)' : '';
  const timeline = [];
  let count = 0;
  const participant = (name, guid) => {
    if (!name || (group ? !names.has(name.toLowerCase()) : !/^0x0000[0-9a-f]+$/i.test(guid))) return null;
    if (!totals.has(name)) totals.set(name, {name, damage: 0, taken: 0, healing: 0, interrupts: 0, deaths: 0});
    return totals.get(name);
  };

  for (const event of reportEvents) {
    const [, kind, source, target, , amount, , sourceId, targetId] = event;
    const actor = participant(source, sourceId);
    const victim = participant(target, targetId);
    if (isDamage(kind)) {
      if (actor) actor.damage += amount;
      if (victim) victim.taken += amount;
    }
    if (kind.endsWith('_HEAL') && actor) actor.healing += amount;
    if (kind === 'SPELL_INTERRUPT' && actor) actor.interrupts++;
    if (kind === 'UNIT_DIED' && victim) victim.deaths++;

    // Retain enemy casts and aura changes even when neither endpoint is a player.
    count++;
    if (timeline.length >= 250) continue;
    timeline.push(timelineEntry(event));
  }
  const rows = [...totals.values()].sort((a, b) => b.damage - a.damage);
  field('combat-totals').replaceChildren(...rows.map(row => {
    const tr = node('tr');
    const rate = (amount) => duration ? format.format(amount / duration) : '—';
    const name = node('th', row.name);
    name.className = classStyle(row.name);
    const remove = node('button', '×');
    remove.type = 'button';
    remove.className = 'combat-remove-character';
    remove.setAttribute('aria-label', 'Remove ' + row.name + ' from this log');
    remove.addEventListener('click', () => showLogDialog({
      title: 'Remove character',
      message: `Remove ${row.name} and their events from this saved session/log?`,
      confirmLabel: 'Remove character',
      onConfirm: () => editWindow({action: 'exclude-character', name: row.name}),
    }));
    name.prepend(remove);
    tr.append(name, ...[format.format(row.damage), rate(row.damage),
      format.format(row.taken), format.format(row.healing), rate(row.healing),
      row.interrupts, row.deaths].map(value => node('td', value)));
    return tr;
  }));
  field('combat-charts').replaceChildren(chart('Damage dealt', rows, 'damage'),
    chart('Damage taken', rows, 'taken'), chart('Effective healing', rows, 'healing'));
  const scope = field('breakdown-character');
  const selected = scope.value;
  scope.replaceChildren(new Option('Group total', ''), ...rows.map(row => new Option(row.name)));
  if ([...scope.options].some(option => option.value === selected)) scope.value = selected;
  renderBreakdown(merged, rows.map(row => row.name));
  field('combat-events').replaceChildren(...timeline);
  field('event-count').textContent = rows.length
    ? `Showing ${timeline.length} of ${count} captured events.`
    : `No matching characters in this window. Showing ${timeline.length} of ${count} captured events.`;
}

field('import-log').addEventListener('submit', handle(async (event) => {
  const fromClient = event.submitter?.id === 'import-client-log';
  const buttons = event.target.querySelectorAll('button');
  for (const button of buttons) button.disabled = true;
  try {
    const file = field('log-file').files[0];
    if (!fromClient && (!file || file.size > 4 * 1024 * 1024)) throw new Error('Choose a combat log up to 4 MiB.');
    const title = field('log-title').value.trim();
    const options = {title, dungeon: field('dungeon-run').checked};
    const payload = fromClient ? {...options, action: 'import-client'} :
      {...options, action: 'save', title: title || file.name.slice(0, 120), body: await file.text()};
    const {id} = await request('/api/combat-logs', payload);
    await list(id);
    event.target.reset();
  } finally { for (const button of buttons) button.disabled = false; }
}));
field('saved-log').addEventListener('change', handle(openLog));
field('window').addEventListener('submit', handle(render));
field('combat-group').addEventListener('change', handle(render));
function showLogDialog({title, message, confirmLabel, initialName, onConfirm}) {
  const dialog = field('log-dialog');
  if (dialog.open) return;
  field('dialog-title').textContent = title;
  field('dialog-message').textContent = message;
  field('rename-field').hidden = initialName === undefined;
  field('new-log-title').value = initialName ?? '';
  field('dialog-confirm').textContent = confirmLabel;
  dialog.returnValue = '';
  dialog.addEventListener('close', handle(async () => {
    if (dialog.returnValue === 'confirm') await onConfirm();
  }), {once: true});
  dialog.showModal();
}

function editLog(action) {
  const id = field('saved-log').value;
  const rename = action === 'rename';
  showLogDialog({
    title: rename ? 'Rename log' : 'Delete log',
    message: rename ? '' : `Delete “${report.title}”? This cannot be undone.`,
    confirmLabel: rename ? 'Save name' : 'Delete log',
    initialName: rename ? report.title : undefined,
    onConfirm: async () => {
      const title = field('new-log-title').value;
      await request('/api/combat-logs', {action, id, title});
      if (rename && field('saved-log').value === id) {
        const option = field('saved-log').selectedOptions[0];
        option.textContent = title.trim() + ' · ' + option.textContent.split(' · ').at(-1);
        report.title = title.trim();
        field('report-title').textContent = report.title;
      } else await list();
    },
  });
}

field('delete-log').addEventListener('click', () => editLog('delete'));
field('rename-log').addEventListener('click', () => editLog('rename'));
field('boss-only').addEventListener('change', handle(render));
field('breakdown-category').addEventListener('change', handle(render));
field('breakdown-character').addEventListener('change', handle(render));
handle(async () => {
  session = await request('/api/session');
  for (const group of session.groups.groups) field('combat-group').add(new Option(group.name, group.id));
  await list();
  const {snapshot} = await request('/api/snapshot');
  for (const view of Object.values(snapshot?.views || {})) {
    for (const character of view.characters || []) classes.set(character.name.toLowerCase(), character.class_id);
  }
  render();
})();

field('combat-session').addEventListener('change', handle(() => { selectSession(); render(); }));
field('combat-gap').addEventListener('change', handle(() => { updateSessions(); selectSession(); render(); }));
for (const id of ['from', 'to']) {
  field(id).addEventListener('input', () => { field('combat-session').selectedIndex = -1; });
}

request('/api/models/config').then(data => {
  field('import-client-log').hidden = !data.config?.client_path;
}).catch(() => {});


async function editWindow(payload) {
  const id = field('saved-log').value;
  const selected = field('combat-session').value;
  const start = field('from').value, end = field('to').value;
  const bossOnly = field('boss-only').checked;
  const result = await request('/api/combat-logs', {id, ...payload});
  if (field('saved-log').value !== id) return;
  if (payload.action === 'copy-window') {
    await list(result.id);
  } else {
    await openLog();
    if (field('saved-log').value !== id) return;
    field('combat-session').value = payload.action === 'name-window' ? start + ',' + end : selected;
    field('from').value = start;
    field('to').value = end;
    field('boss-only').checked = bossOnly;
    render();
  }
}

for (const action of ['name-window', 'copy-window']) {
  field(action).addEventListener('click', handle(async () => {
    if (!field('window').reportValidity()) return;
    const start = Number(field('from').value), end = Number(field('to').value);
    const title = prompt(action === 'name-window' ? 'Name this time window' : 'Name the separate log');
    if (title?.trim()) await editWindow({action, start, end, title: title.trim()});
  }));
}
