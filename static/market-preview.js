'use strict';

const form = document.querySelector('#market-search');
const field = document.querySelector('#market-item');
const rows = document.querySelector('#market-rows');
const mode = document.querySelector('#market-mode');
const statusLine = document.querySelector('#market-status');
let requestId = 0;

async function refreshMarket() {
  const id = ++requestId;
  statusLine.textContent = 'Loading market comparison...';
  try {
    const response = await fetch('/api/market-preview?' + new URLSearchParams({q: field.value.trim()}));
    const data = await response.json();
    if (id !== requestId) return;
    if (!response.ok) throw new Error(data.error);
    const {snapshot, rows: items, status, reset, local_unavailable} = data.result;
    if (status.publisher === 'not_connected') {
      mode.textContent = 'Market pricing is not connected to AHBot Plus. Suggested prices are for preview only.';
    } else if (status.active_price_set) {
      mode.textContent = 'Publisher: ' + status.publisher + ' | ' + status.active_price_set.count + ' published unit prices'
        + (status.active_price_set.reason ? ' | ' + status.active_price_set.reason : '');
    } else {
      mode.textContent = 'Publisher status unavailable.';
    }
    document.querySelector('#market-reset').textContent = reset
      ? 'Reset preview: ' + Number(reset.unbid).toLocaleString() + ' unbid bot auctions eligible, '
        + Number(reset.with_bid).toLocaleString() + ' bid-bearing bot auctions protected.'
      : '';
    const feeds = document.querySelector('#market-feeds');
    feeds.replaceChildren();
    for (const feed of Object.values(status.feeds)) {
      const entry = document.createElement('li');
      entry.textContent = feed.label + ' | ' + feed.health
        + (feed.stamp ? ' | ' + new Date(feed.stamp).toLocaleString() + ' | ' + Number(feed.items).toLocaleString() + ' items' : '')
        + (feed.error ? ' | ' + feed.error : '');
      feeds.append(entry);
    }
    rows.replaceChildren();
    if (!snapshot) {
      statusLine.textContent = 'Waiting for the first market snapshot.';
      return;
    }
    const age = Math.max(0, Math.floor((Date.now() - snapshot.stamp) / 60000));
    const freshness = status.feed === 'stale' ? 'Feed stale' : 'Recent market snapshot';
    statusLine.textContent = freshness + ' | ' + new Date(snapshot.stamp).toLocaleString()
      + ' | ' + age + ' min old | ' + snapshot.item_count.toLocaleString() + ' items'
      + (items.length ? '' : ' | No matching items')
      + (local_unavailable ? ' | Azeroth-2 comparison unavailable' : '');
    for (const item of items) {
      const row = rows.insertRow();
      const link = document.createElement('a');
      link.href = 'https://www.wowhead.com/wotlk/item=' + item.item_id;
      link.textContent = (item.local?.name || item.name) + ' (#' + item.item_id + ')';
      row.insertCell().append(link);
      for (const value of [item.ask, item.median, item.listed, item.vol24, item.sure24, item.last_sold_price, item.last_sold_at ? new Date(item.last_sold_at).toLocaleString() : null, item.local?.ask, item.proposed, item.published_price, item.price_source]) {
        row.insertCell().textContent = value == null ? '-' : value.toLocaleString();
      }
    }
  } catch (error) {
    if (id === requestId) statusLine.textContent = error.message;
  }
}

form.addEventListener('submit', event => {
  event.preventDefault();
  refreshMarket();
});
refreshMarket();

const archivePanel = document.querySelector('#market-archive');
const archiveStatus = document.querySelector('#market-archive-status');
const archiveRows = document.querySelector('#market-archive-rows');
const archiveMore = document.querySelector('#market-archive-more');
let archiveCursor = null;
let archiveBusy = false;

async function loadArchive(older = false) {
  if (archiveBusy) return;
  archiveBusy = true;
  archiveMore.disabled = true;
  try {
    const query = older ? '?before=' + archiveCursor : '';
    const response = await fetch('/api/market-preview/snapshots' + query);
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    if (!older) archiveRows.replaceChildren();
    for (const item of body.result.snapshots) {
      const row = archiveRows.insertRow();
      row.insertCell().textContent = new Date(item.stamp).toLocaleString();
      row.insertCell().textContent = item.item_count.toLocaleString();
      const cell = row.insertCell();
      for (const [format, label] of [['json.gz', 'Compressed JSON'], ['json', 'JSON']]) {
        const link = document.createElement('a');
        link.textContent = label;
        link.href = '/api/market-preview/download?' + new URLSearchParams({stamp: item.stamp, format});
        if (cell.childNodes.length) cell.append(' | ');
        cell.append(link);
      }
    }
    archiveCursor = body.result.next_before;
    archiveMore.hidden = archiveCursor == null;
    archiveStatus.textContent = archiveRows.rows.length ? '' : 'No snapshots archived yet.';
  } catch (error) {
    archiveStatus.textContent = error.message;
  } finally {
    archiveBusy = false;
    archiveMore.disabled = false;
  }
}

archivePanel.addEventListener('toggle', () => {
  if (archivePanel.open) loadArchive();
});
archiveMore.addEventListener('click', () => loadArchive(true));

const coverage = document.querySelector('#market-coverage');
coverage.addEventListener('toggle', async () => {
  if (!coverage.open) return;
  const scope = document.querySelector('#market-coverage-scope');
  const counts = document.querySelector('#market-coverage-counts');
  scope.textContent = 'Checking price coverage...';
  try {
    const response = await fetch('/api/market-preview/coverage');
    const body = await response.json();
    if (!response.ok) throw new Error(body.error);
    const result = body.result;
    counts.replaceChildren();
    if (result.scope === 'unavailable') {
      scope.textContent = 'No AHBot Plus stock catalogue available.';
      return;
    }
    scope.textContent = result.total.toLocaleString() + ' distinct items in '
      + (result.scope === 'configured_candidates' ? 'the AHBot Plus candidate catalogue.'
        : 'current bot listings. The full candidate catalogue is unavailable.');
    const categories = [
      ['live', 'Usable live price', 'The feed is fresh, with enough price observations or recent inferred bag sales for a price that passes the import rules.'],
      ['historical_only', 'Usable historical price only', 'No usable fresh price is available. Our archive has enough observations to calculate a price that passes the import rules.'],
      ['anniversary', 'Usable Anniversary fallback', 'Anniversary has a Thunderstrike listing price and enough EU regional sale activity to qualify.'],
      ['policy_excluded', 'Excluded by price policy', 'The item appeared in the feed but falls outside our import rules, such as the stackable-goods and regular-bags scope or safe stack price limit.'],
      ['insufficient_data', 'Seen, insufficient observations', 'The item passes the item eligibility rules, but we have too few price observations for a usable price.'],
      ['never_seen', 'Never seen in our archived feed', 'The item has not appeared in our archived Forever snapshots and has no qualifying Anniversary fallback.'],
    ];
    for (const [field, label, description] of categories) {
      const tile = document.createElement('div');
      const term = document.createElement('dt');
      const subtitle = document.createElement('small');
      const value = document.createElement('dd');
      term.textContent = label;
      subtitle.textContent = description;
      term.append(subtitle);
      value.textContent = result[field].toLocaleString();
      tile.append(term, value);
      counts.append(tile);
    }
  } catch (error) {
    scope.textContent = error.message;
  }
});
