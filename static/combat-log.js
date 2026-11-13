const field = (id) => document.getElementById(id);
const format = new Intl.NumberFormat(undefined, {maximumFractionDigits: 1});
let session;
let report;
let reportEvents = [];
const classes = new Map();
const classStyle = name => 'combat-character class-' + (classes.get(name) || 0);
let generation = 0;

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
    ...result.map(([id, title, date]) => new Option(`${title} · ${date} UTC`, id)));
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
  field('report-title').textContent = report.title;
  field('from').value = '0';
  field('to').value = report.events.reduce((latest, event) => Math.max(latest, event[0]), 0);
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

function chart(title, rows, key) {
  const section = node('section');
  section.append(node('h3', title));
  const max = Math.max(1, ...rows.map(row => row[key]));
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
  reportEvents = report.events.filter(([time]) => merged.some(([a,b]) => time >= a && time <= b));
  const timeline = [];
  let count = 0;
  const participant = (name, guid) => {
    if (!name || (group ? !names.has(name.toLowerCase()) : !/^0x0000[0-9a-f]+$/i.test(guid))) return null;
    if (!totals.has(name)) totals.set(name, {name, damage: 0, taken: 0, healing: 0, interrupts: 0, deaths: 0});
    return totals.get(name);
  };

  for (const [time, kind, source, target, spell, amount, spellId, sourceId, targetId] of reportEvents) {
    if (time < start || time > end) continue;
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
    const item = node('li', `${time.toFixed(3)}s · ${source || '—'} → ${target || '—'} · ${kind.replaceAll('_', ' ').toLowerCase()} `);
    if (spellId > 0) item.append(wowheadLink(spell, 'spell', spellId));
    else item.append(document.createTextNode(spell));
    if (amount) item.append(document.createTextNode(` · ${format.format(amount)}`));
    timeline.push(item);
  }
  const rows = [...totals.values()].sort((a, b) => b.damage - a.damage);
  field('combat-totals').replaceChildren(...rows.map(row => {
    const tr = node('tr');
    const rate = (amount) => duration ? format.format(amount / duration) : '—';
    const name = node('th', row.name);
    name.className = classStyle(row.name);
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
  const button = event.target.querySelector('button');
  button.disabled = true;
  try {
    const file = field('log-file').files[0];
    if (!file || file.size > 4 * 1024 * 1024) throw new Error('Choose a combat log up to 4 MiB.');
    const title = field('log-title').value.trim() || file.name.slice(0, 120);
    const {id} = await request('/api/combat-logs', {action: 'save', title, body: await file.text(), dungeon: field('dungeon-run').checked});
    await list(id);
    event.target.reset();
  } finally { button.disabled = false; }
}));
field('saved-log').addEventListener('change', handle(openLog));
field('window').addEventListener('submit', handle(render));
field('combat-group').addEventListener('change', handle(render));
function editLog(action) {
  const id = field('saved-log').value;
  const dialog = field('log-dialog');
  const rename = action === 'rename';
  field('dialog-title').textContent = rename ? 'Rename log' : 'Delete log';
  field('dialog-message').textContent = rename ? '' : `Delete “${report.title}”? This cannot be undone.`;
  field('rename-field').hidden = !rename;
  field('new-log-title').value = report.title;
  field('dialog-confirm').textContent = rename ? 'Save name' : 'Delete log';
  dialog.returnValue = '';
  dialog.addEventListener('close', handle(async () => {
    if (dialog.returnValue !== 'confirm') return;
    const title = field('new-log-title').value;
    await request('/api/combat-logs', {action, id, title});
    if (rename && field('saved-log').value === id) {
      const option = field('saved-log').selectedOptions[0];
      option.textContent = title.trim() + ' · ' + option.textContent.split(' · ').at(-1);
      report.title = title.trim();
      field('report-title').textContent = report.title;
    } else await list();
  }), {once: true});
  dialog.showModal();
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
    for (const character of view.characters || []) classes.set(character.name, character.class_id);
  }
  render();
})();
