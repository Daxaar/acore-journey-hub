'use strict';

const guild = document.querySelector('#tax-guild');
const period = document.querySelector('#tax-period');
const status = document.querySelector('#tax-status');
const details = document.querySelector('#tax-details');
let character = 0;
let selectedName = '';
let request = 0;

function coins(value){
 const span=document.createElement('span');span.className='money';
 let copper=Math.max(0,Math.round(Number(value)||0));
 const gold=Math.floor(copper/10000),silver=Math.floor(copper%10000/100);copper%=100;
 span.setAttribute('aria-label',gold+' gold, '+silver+' silver, '+copper+' copper');
 for(const [amount,type,show] of [[gold,'gold',gold>0],[silver,'silver',silver>0||gold>0],[copper,'copper',copper>0||(!gold&&!silver)]]){
  if(!show)continue;
  const icon=document.createElement('i');icon.className='coin '+type;icon.setAttribute('aria-hidden','true');
  span.append(document.createTextNode(amount.toLocaleString()),icon);
 }
 return span;
}

function cell(row, value) {
  const td = row.insertCell();
  td.textContent = value ?? '';
  return td;
}

async function refresh() {
  const current = ++request;
  status.textContent = 'Loading contributions…';
  try {
    const query = new URLSearchParams({guild: guild.value || '0', period: period.value, character});
    const response = await fetch('/api/guild-tax?' + query);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error);
    if (current !== request) return;
    const report = payload.result;
    guild.replaceChildren(new Option('All guilds', 0), ...report.guilds.map(entry => new Option(entry.name, entry.id)));
    guild.value = String(report.guild);
    const rates = document.querySelector('#tax-rates');
    rates.hidden = !report.can_edit_rates;
    if (!rates.hidden && !guildRows.childElementCount) renderGuilds(report.guilds);
    const health = report.health;
    const pct = (100 * (health.rate || 0)).toFixed(1);
    status.textContent = report.guild ? [
      health.alert ? 'High tax error rate.' : '',
      `Last 24 hours · ${pct}% errors across ${health.checked} checked · ${health.mismatches} mismatches · ${health.failed} failures · ${health.unverifiable} unverifiable · observed balance difference ${health.copper_delta} copper. Most recent five minutes excluded.`,
    ].join(' ').trim() : '';
    const ranks = document.querySelector('#tax-ranks');
    ranks.replaceChildren();
    const allGuilds = !report.guild;
    document.querySelector('#tax-name-heading').textContent = allGuilds ? 'Guild' : 'Character';
    document.querySelector('#tax-level-heading').hidden = allGuilds;
    document.querySelector('#tax-rate-heading').hidden = !allGuilds;
    const entries = allGuilds ? report.summary : report.ranks;
    for (const entry of entries) {
      const row = ranks.insertRow();
      const link = document.createElement('button');
      link.type = 'button';
      link.className = allGuilds ? 'tax-character' : 'tax-character class-' + entry.class;
      link.textContent = entry.name;
      link.addEventListener('click', () => {
        if (allGuilds) {
          guild.value = String(entry.id);
          character = 0;
        } else {
          character = entry.guid;
          selectedName = entry.name;
        }
        refresh();
      });
      const name = cell(row, '');
      if (allGuilds && (entry.faction === 'Alliance' || entry.faction === 'Horde')) {
        const icon = document.createElement('img');
        icon.src = '/faction-' + entry.faction.toLowerCase() + '.png';
        icon.alt = entry.faction;
        icon.title = entry.faction;
        icon.className = 'tax-faction-icon';
        icon.addEventListener('error', () => { icon.hidden = true; }, {once: true});
        name.append(icon);
      }
      name.append(link);
      if (allGuilds) cell(row, entry.rate == null ? 'Unavailable' : entry.rate + '%');
      else cell(row, entry.level);
      cell(row, '').append(coins(entry.paid));
    }
    document.querySelector('#tax-total').replaceChildren('Total tax paid · ', coins(entries.reduce((sum, entry) => sum + Number(entry.paid), 0)));
    details.hidden = allGuilds || !character;
    document.querySelector('#tax-character').textContent = selectedName;
    const history = document.querySelector('#tax-history');
    history.replaceChildren();
    for (const entry of report.history) {
      const row = history.insertRow();
      cell(row, entry.time);
      cell(row, entry.source);
      for (const value of [entry.gross, entry.tax, entry.net]) cell(row, '').append(coins(value));
      cell(row, entry.state);
    }
  } catch (error) {
    if (current === request) status.textContent = error.message;
  }
}

const guildRows = document.querySelector('#tax-guild-rows');
const search = document.querySelector('#tax-guild-search');
const selectAll = document.querySelector('#tax-select-all');
const rateStatus = document.querySelector('#rate-status');

function filterGuilds() {
  const term = search.value.trim().toLowerCase();
  for (const row of guildRows.rows) row.hidden = !row.dataset.search.includes(term);
  const visible = [...guildRows.rows].filter(row => !row.hidden);
  const checked = visible.filter(row => row.querySelector('input').checked).length;
  selectAll.checked = visible.length > 0 && checked === visible.length;
  selectAll.indeterminate = checked > 0 && checked < visible.length;
}

function renderGuilds(entries) {
  for (const entry of entries) {
    const row = guildRows.insertRow();
    row.dataset.guild = entry.id;
    row.dataset.search = (entry.name + ' ' + entry.faction).toLowerCase();
    const selected = document.createElement('input');
    selected.type = 'checkbox';
    selected.setAttribute('aria-label', 'Select ' + entry.name);
    cell(row).append(selected);
    cell(row, entry.name);
    cell(row, entry.faction);
    cell(row, entry.members);
    const rate = document.createElement('input');
    rate.type = 'number';
    rate.min = '0';
    rate.max = '100';
    rate.step = '1';
    rate.required = true;
    rate.value = entry.rate;
    rate.defaultValue = entry.rate;
    rate.setAttribute('aria-label', entry.name + ' tax rate');
    cell(row).append(rate);
  }
  filterGuilds();
}

search.addEventListener('input', filterGuilds);
guildRows.addEventListener('change', filterGuilds);
selectAll.addEventListener('change', () => {
  const checked = selectAll.checked;
  for (const row of guildRows.rows) {
    if (!row.hidden) row.querySelector('input').checked = checked;
  }
  filterGuilds();
});

document.querySelector('#tax-apply-selected').addEventListener('click', () => {
  const bulk = document.querySelector('#tax-bulk-rate');
  if (!bulk.value || !bulk.reportValidity()) {
    rateStatus.textContent = 'Enter a whole rate from 0 to 100.';
    return;
  }
  const selected = [...guildRows.rows].filter(row => row.querySelector('input').checked);
  for (const row of selected) row.querySelector('input[type=number]').value = bulk.value;
  rateStatus.textContent = selected.length ? 'Rate entered for ' + selected.length + ' guilds. Save to keep the changes.' : 'Select at least one guild.';
});

guild.addEventListener('change', () => { character = 0; refresh(); });
document.querySelector('#tax-rate-form').addEventListener('submit', async event => {
  event.preventDefault();
  const key = document.querySelector('#tax-admin-key');
  const changed = [...guildRows.rows]
    .map(row => [row, row.querySelector('input[type=number]')])
    .filter(([, input]) => input.value !== input.defaultValue);
  if (!changed.length) {
    rateStatus.textContent = 'No rate changes to save.';
    return;
  }
  const rates = changed.map(([row, input]) => ({guild: Number(row.dataset.guild), rate: Number(input.value)}));
  const body = JSON.stringify({rates, key: key.value});
  const submit = event.currentTarget.querySelector('button[type=submit], button:not([type])');
  submit.disabled = true;
  key.value = '';
  try {
    const session = await (await fetch('/api/session')).json();
    const response = await fetch('/api/guild-tax/rate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Dashboard-Token': session.token},
      body,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    changed.forEach(([, input], i) => {
      const draft = input.value;
      input.defaultValue = String(rates[i].rate);
      input.value = draft;
    });
    rateStatus.textContent = 'Saved rates for ' + result.count + ' guild(s). Run .reload config in game to apply.';
    refresh();
  } catch (error) {
    rateStatus.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});
period.addEventListener('change', refresh);
document.querySelector('#transaction-filters').addEventListener('submit', event => { event.preventDefault(); refresh(); });
refresh();
