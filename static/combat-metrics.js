const categories = [
  'Damage Done', 'DPS', 'Friendly Fire', 'Damage Taken', 'Healing Done', 'Absorbs',
  'Healing Taken', 'Overhealing Done', 'Deaths', 'DOT Uptime', 'HOT Uptime',
  'Activity', 'Dispels', 'Dispelled', 'Interrupts', 'Ressers', 'CC Breakers',
  'Mana Gained', 'Energy Gained', 'Rage Gained', 'Runic Power Gained',
];
const powerTypes = {'Mana Gained': 0, 'Rage Gained': 1, 'Energy Gained': 3, 'Runic Power Gained': 6};
const isDamage = (kind) => kind.endsWith('_DAMAGE') || ['DAMAGE_SHIELD', 'DAMAGE_SPLIT'].includes(kind);
const isHeal = (kind) => kind.endsWith('_HEAL');

function combatBreakdown(events, category, start, end, members) {
  const selected = new Set(members);
  const values = [];
  const active = new Map();
  const ticks = new Set();
  const auras = new Map();
  const key = (event) => JSON.stringify([event[7], event[8], event[6]]);
  for (const event of events) {
    if (event[1] === (category === 'DOT Uptime' ? 'SPELL_PERIODIC_DAMAGE' : 'SPELL_PERIODIC_HEAL')) ticks.add(key(event));
  }
  const add = (name, other, spell, value) => {
    if (selected.has(name) && value > 0) values.push({name, other, spell: spell || 'Unknown', value});
  };
  const close = (id, time) => {
    const aura = auras.get(id);
    if (!aura) return;
    const [opened, , source, target, spell] = aura;
    add(source, target, spell, Math.min(end, time) - Math.max(start, opened));
    auras.delete(id);
  };
  for (const event of events) {
    const [time, kind, source, target, spell, amount, , , targetId, extra, absorbed, power, detail, friendly] = event;
    if (time > end) continue;
    if (category.endsWith(' Uptime')) {
      const id = key(event);
      if (kind === 'UNIT_DIED') {
        for (const [auraId, aura] of auras) if (aura[8] === targetId) close(auraId, time);
      } else if (ticks.has(id)) {
        if (kind === 'SPELL_AURA_APPLIED' || kind === 'SPELL_AURA_REFRESH') {
          if (!auras.has(id)) auras.set(id, event);
        } else if (kind === 'SPELL_AURA_REMOVED' || kind.startsWith('SPELL_AURA_BROKEN')) close(id, time);
      }
      continue;
    }
    if (time < start) continue;
    switch (category) {
      case 'Damage Done':
      case 'DPS':
        if (isDamage(kind)) add(source, target, spell, category === 'DPS' ? (end > start ? amount / (end - start) : 0) : amount);
        break;
      case 'Friendly Fire': if (isDamage(kind) && friendly && event[7] !== targetId) add(source, target, spell, amount); break;
      case 'Damage Taken': if (isDamage(kind)) add(target, source, spell, amount); break;
      case 'Healing Done': if (isHeal(kind)) add(source, target, spell, amount); break;
      case 'Healing Taken': if (isHeal(kind)) add(target, source, spell, amount); break;
      case 'Overhealing Done': if (isHeal(kind)) add(source, target, spell, extra); break;
      case 'Absorbs': add(target, source, spell, absorbed); break;
      case 'Deaths': if (kind === 'UNIT_DIED') add(target, '', 'Death', 1); break;
      case 'Dispels':
      case 'Dispelled':
        if (kind === 'SPELL_DISPEL' || kind === 'SPELL_STOLEN') {
          if (category === 'Dispels') add(source, target, detail || spell, 1);
          else add(target, source, detail || spell, 1);
        }
        break;
      case 'Interrupts': if (kind === 'SPELL_INTERRUPT') add(source, target, detail || spell, 1); break;
      case 'Ressers': if (kind === 'SPELL_RESURRECT') add(source, target, spell, 1); break;
      case 'CC Breakers': if (kind.startsWith('SPELL_AURA_BROKEN')) add(source, target, detail || spell, 1); break;
      case 'Activity':
        if (selected.has(source) && (isDamage(kind) || isHeal(kind) || kind === 'SPELL_CAST_SUCCESS' || kind.endsWith('_MISSED'))) {
          if (!active.has(source)) active.set(source, new Set());
          active.get(source).add(Math.floor(time - start));
        }
        break;
      default: if (power === powerTypes[category]) add(target, source, spell, amount);
    }
  }
  for (const id of auras.keys()) close(id, end);
  for (const [name, seconds] of active) add(name, '', 'Active one-second intervals', seconds.size);
  return values;
}

function renderBreakdown(windows, members) {
  const category = field('breakdown-category').value;
  const scope = field('breakdown-character').value;
  const duration = windows.reduce((sum,[a,b]) => sum+b-a,0);
  const metric = category === 'DPS' ? 'Damage Done' : category;
  const values = windows.flatMap(([start,end]) =>
    combatBreakdown(report.events, metric, start, end, scope ? [scope] : members));
  if (category === 'DPS') for (const row of values) row.value = duration ? row.value / duration : 0;
  const total = values.reduce((sum, row) => sum + row.value, 0);
  const units = category.endsWith(' Uptime') ? ' cumulative aura-seconds' :
    category === 'Activity' ? ' active character-seconds' : category === 'DPS' ? ' DPS' : '';
  const notes = {
    'Absorbs': 'Absorbed damage credited to the protected character. Wrath damage events do not identify the shield caster.',
    'Activity': 'Counts one-second intervals containing outgoing damage, healing, misses or successful casts.',
    'DOT Uptime': 'Estimated from recorded aura boundaries and matching damage ticks. Overlapping targets add together.',
    'HOT Uptime': 'Estimated from recorded aura boundaries and matching healing ticks. Overlapping targets add together.',
    'CC Breakers': 'Counts explicit aura-break events only.',
  };
  field('breakdown-note').textContent = `${format.format(total)}${units} · ${scope || 'Group total'}. ${notes[category] || ''}`;
  const note = field('breakdown-note');
  if (scope) {
    const back = node('button', '← Group total');
    back.type = 'button';
    back.className = 'subtle-button combat-back';
    back.addEventListener('click', () => {
      field('breakdown-character').value = '';
      render();
      field('breakdown-character').focus();
    });
    note.prepend(back);
  }
  const breakdown = field('breakdown');
  breakdown.replaceChildren();
  if (!values.length) {
    breakdown.append(node('p', 'No matching events recorded in this window.'));
    return;
  }
  const spellIcons = new Map(report.events.filter(event => report.icons[event[6]])
    .map(event => [event[4], report.icons[event[6]]]));
  const breakdownChart = (title, key, entries = values, select) => {
    const grouped = new Map();
    const subtotal = entries.reduce((sum, entry) => sum + entry.value, 0);
    for (const entry of entries) {
      if (entry[key]) grouped.set(entry[key], (grouped.get(entry[key]) || 0) + entry.value);
    }
    return chart(title, [...grouped].map(([name, value]) => ({name, value}))
      .sort((a, b) => b.value - a.value).slice(0, 12)
      .map(row => ({...row,
        character: key === 'name' || key === 'other' ? row.name : '',
        select: select && (() => select(row.name)),
        icon: key === 'spell' ? spellIcons.get(row.name) : '',
        name: `${row.name} (${format.format(subtotal ? 100 * row.value / subtotal : 0)}%)`})), 'value');
  };
  if (!scope) breakdown.append(breakdownChart('By character', 'name', values, name => {
    field('breakdown-character').value = name;
    render();
    field('breakdown-note').querySelector('button').focus();
  }));
  const filter = node('select');
  filter.className = 'combat-source-filter';
  filter.setAttribute('aria-label', 'Filter abilities by source or target');
  filter.append(new Option('All sources and targets', ''));
  for (const name of [...new Set(values.map(row => row.other).filter(Boolean))].sort()) filter.add(new Option(name));
  const abilities = node('div');
  function showAbilities() {
    const entries = filter.value ? values.filter(row => row.other === filter.value) : values;
    abilities.replaceChildren(breakdownChart('By ability · top 12', 'spell', entries));
  }
  filter.addEventListener('change', showAbilities);
  const detail = node('div');
  detail.append(filter, abilities);
  showAbilities();
  breakdown.append(breakdownChart('By source or target · top 12', 'other', values, name => {
    filter.value = name;
    showAbilities();
  }), detail);
}

for (const category of categories) document.getElementById('breakdown-category').add(new Option(category));
