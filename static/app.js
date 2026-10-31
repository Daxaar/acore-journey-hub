"use strict";

const state = { snapshot: null, view: "party", selected: null, filter: "all", search: "", timer: null,
  busy: false, error: null, lastSuccess: null, token: null, watched: [], notes: {}, noteImages: {}, groups: null, groupBusy: false, editingGroup: null };
const $ = (id) => document.getElementById(id);
const labels = { ready: "✓ Ready to hand in", active: "In progress", failed: "Failed",
  rewarded: "✓ Handed in", missing: "—", unavailable: "Offline · unavailable" };
const icons = { kill: "⚔", interact: "◇", item: "▣", exploration: "⌖", pvp: "⚔", money: "◉",
  reputation: "⚑", timer: "◷", event: "✧" };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function view() { return state.snapshot?.views[state.view]; }
function className(c) { return `class-${c.class_id || 0}`; }
function portrait(c) { return el("span", "portrait", c.name.slice(0, 1)); }

function characterHead(c) {
  const head = el("div", "character-head");
  head.append(portrait(c));
  const text = el("div");
  text.append(el("span", "character-name", c.name),
    el("span", "character-subtitle", c.found ? `Level ${c.level} ${c.class_name}` : "Character not found"));
  head.append(text);
  return head;
}

function selectCharacter(name) {
  state.selected = name;
  render();
}

let restedTooltipAnchor = null;
function hideRestedTooltip() {
  restedTooltipAnchor?.removeAttribute('aria-describedby');
  restedTooltipAnchor = null;
  $('rested-xp-tooltip').hidden = true;
}
function showRestedTooltip(indicator, anchor = indicator, event = null) {
  hideRestedTooltip();
  const tip = $('rested-xp-tooltip');
  const lines = indicator.dataset.tooltipText.split('\n');
  tip.replaceChildren(el('h3', 'tooltip-requirement', 'Rested XP'),
    ...lines.map((text, index) => el('p', index === 0 || index === lines.length - 1 ? 'tooltip-note' : '', text)));
  tip.hidden = false;
  restedTooltipAnchor = anchor;
  anchor.setAttribute('aria-describedby', tip.id);
  ItemTooltip.position(tip, indicator, event);
}
window.addEventListener('resize', hideRestedTooltip);
document.addEventListener('scroll', hideRestedTooltip, true);
document.addEventListener('keydown', event => { if (event.key === 'Escape') hideRestedTooltip(); });

function restedIndicator(c) {
  const r = c.rested;
  const indicator = el('span', 'rested-xp');
  if (!r || r.state === 'unavailable') {
    indicator.textContent = 'Rested —';
    indicator.dataset.tooltipText = 'Rested XP data unavailable.';
  } else if (r.state === 'max_level') {
    indicator.textContent = 'Max level';
    indicator.dataset.tooltipText = 'Rested XP does not accumulate at the configured maximum level.';
  } else {
    const pct = n => n.toLocaleString(undefined, {maximumFractionDigits: 1});
    const xp = n => n.toLocaleString();
    indicator.textContent = `Rested ${r.estimated ? '≈' : ''}${pct(r.level_percent)}%`;
    indicator.dataset.tooltipText = `${r.estimated ? 'Estimated including offline rest' : 'Latest saved rested XP'}
`
      + `Rested coverage: ${xp(r.coverage_xp)} XP (${pct(r.level_percent)}% of the current level requirement).
`
      + `Bonus XP available: ${xp(r.bonus_xp)} extra XP from eligible kills.
`
      + `Cap: ${pct(r.cap_full_percent)}% full; ${pct(r.remaining_percent)} percentage points of coverage remaining (cap ${pct(r.cap_percent)}%).
`
      + 'Coverage uses current-level equivalents; subsequent levels require different amounts of XP.';
  }
  indicator.setAttribute('aria-label', indicator.dataset.tooltipText);
  indicator.classList.add('tooltip-trigger');
  indicator.addEventListener('mouseenter', event => showRestedTooltip(indicator, indicator, event));
  indicator.addEventListener('mousemove', event => {
    if ($('rested-xp-tooltip').hidden || restedTooltipAnchor !== indicator) showRestedTooltip(indicator, indicator, event);
    else ItemTooltip.position($('rested-xp-tooltip'), indicator, event);
  });
  indicator.addEventListener('mouseleave', hideRestedTooltip);
  return indicator;
}

function renderRoster(data) {
  hideRestedTooltip();
  const roster = $("roster");
  const cards = data.characters.map((c) => {
    const selected = c.name === state.selected;
    const card = el("button", `character-card ${className(c)}${selected ? " selected" : ""}`
      + (c.found ? "" : " missing-character"));
    card.type = "button";
    card.id = `character-${c.name}`;
    card.setAttribute("aria-pressed", String(selected));
    card.setAttribute("aria-label", `${c.name}, ${c.found ? `level ${c.level} ${c.class_name}, `
      + `${c.active} active quests, ${c.ready} ready to hand in` : "not found in the database"}`);
    card.addEventListener("click", () => selectCharacter(c.name));
    card.append(characterHead(c));
    const meta = el("div", "character-meta");
    meta.append(el("span", `dot${c.online ? " online" : ""}`),
      document.createTextNode(c.found ? `${c.online ? "Online" : "Offline"} · ${c.race}` : "Check character name"));
    const foot = el("div", "character-foot");
    const active = el("span");
    active.append(el("b", "", c.active), document.createTextNode(" quests"));
    foot.append(active, ...(c.found ? [restedIndicator(c)] : []), el("span", c.ready ? "ready" : "",
      c.quest_state_available === false ? "Live state unavailable" : `${c.ready} ready`));
    if (c.found) {
      const indicator = foot.querySelector('.rested-xp');
      const restedText = indicator.dataset.tooltipText;
      card.addEventListener('focus', () => showRestedTooltip(indicator, card));
      card.addEventListener('blur', hideRestedTooltip);
      card.addEventListener('mouseleave', hideRestedTooltip);
      card.setAttribute('aria-label', card.getAttribute('aria-label') + '. ' + restedText);
    }
    card.append(meta, foot);
    if (state.view === 'bots') {
      const wrapper = el('div','watch-card');
      const note = el('button','watch-note-button','✎ Note'); note.type = 'button';
      note.dataset.noteName = c.name; note.setAttribute('aria-label','Note for '+c.name);
      note.setAttribute('aria-haspopup','dialog'); note.setAttribute('aria-controls','watch-note-dialog');
      note.classList.toggle('has-note',Boolean(noteFor(c.name)||noteImageFor(c.name)));
      if(noteImageFor(c.name)){note.textContent='✎ Note · image';note.setAttribute('aria-label','View or edit note and image for '+c.name);}
      note.title = noteFor(c.name)||noteImageFor(c.name) ? 'Edit saved note for '+c.name : 'Add a note for '+c.name;
      note.addEventListener('click',()=>openWatchNote(c));
      wrapper.append(card,note); return wrapper;
    }
    return card;
  });
  roster.replaceChildren(...(cards.length ? cards : [
    el("div", "loading-card", "No bots selected. Add any character name above to begin watching.")]));
  roster.setAttribute("aria-busy", "false");
}

function statusBadge(progress) {
  const isBehind = progress.behind;
  const node = el("span", `status-badge ${progress.status}${isBehind ? " behind" : ""}`,
    isBehind ? "⚑ Catch up" : labels[progress.status]);
  if (progress.status === "missing") node.title = "Not in the saved active quest log";
  if (progress.explanation) {
    node.title = progress.explanation.reasons.join(" ");
    if (progress.status === "missing") node.textContent = progress.explanation.confidence === "blocked" ? "Requirement not met" : "Availability unverified";
  }
  if (isBehind) node.title = "Unfinished while another participant is ahead or ready to hand in";
  return node;
}

function objectiveCell(progress, objective, selected) {
  const behind = progress.behind_objectives.includes(objective.key);
  const td = el("td", `${selected ? "selected-column " : ""}${behind ? "behind-cell" : ""}`);
  const current = progress.counts[objective.key];
  if (["missing", "rewarded", "unavailable"].includes(progress.status)) {
    td.append(el("span", "progress-value muted", progress.status === "rewarded" ? "✓" : "—"));
    td.title = progress.status === "rewarded" ? "Handed in; historical objective counts are unavailable"
      : "Not in saved active quest log";
  } else if (current === null || current === undefined) {
    td.append(el("span", "progress-value muted", progress.status === "ready" ? "✓" : "Status only"));
    td.title = objective.note || "No numeric counter is available";
  } else {
    const done = current >= objective.required;
    let text = `${current} / ${objective.required}`;
    if (objective.kind === "exploration") text = done ? "✓ Explored" : "Not explored";
    td.append(el("span", `progress-value${done ? " done" : ""}${behind ? " behind" : ""}`, text));
    const meter = el("span", "meter");
    const amount = Math.min(100, Math.max(0, Math.round(current / objective.required * 10) * 10));
    meter.setAttribute("aria-hidden", "true");
    meter.append(el("span", `meter-fill p${amount}${done ? " done" : ""}`));
    td.append(meter);
    if (behind) td.title = "Behind another participant on this objective";
  }
  return td;
}

function filteredQuests(data) {
  return data.quests.filter((q) => {
    if (state.filter === "shared" && !q.shared) return false;
    if (state.filter === "attention" && !q.attention) return false;
    if (state.filter === "ready" && !q.ready_count) return false;
    if (!state.search) return true;
    const text = `${q.id} ${q.title} ${q.objectives.map((o) => o.label).join(" ")}`;
    return text.toLocaleLowerCase().includes(state.search);
  });
}

function renderTable(data) {
  const wrap = $("table-wrap");
  const { scrollLeft, scrollTop } = wrap;
  const quests = filteredQuests(data);
  $("quest-count").textContent = `${quests.length} of ${data.quests.length} quests`;
  if (!quests.length) {
    let message = "No quests match this view. Try another filter or search.";
    if (!data.quests.length) {
      message = "No active quests in the saved logs. Unsaved gameplay may take 15 minutes to appear.";
    }
    wrap.replaceChildren(el("div", "empty-state", message));
    return;
  }
  const table = el("table", "comparison-table");
  const caption = el("caption", "sr-only", "Saved quest objectives compared for each character");
  table.append(caption);
  const thead = el("thead");
  const headings = el("tr");
  const objectiveHeading = el("th", "", "QUEST & OBJECTIVE");
  objectiveHeading.scope = "col";
  headings.append(objectiveHeading);
  for (const c of data.characters) {
    const th = el("th", `${className(c)}${c.name === state.selected ? " selected-column" : ""}`);
    th.scope = "col";
    th.append(el("strong", "table-name", c.name), el("span", "", c.found ? `LVL ${c.level}` : "NOT FOUND"));
    headings.append(th);
  }
  thead.append(headings);
  table.append(thead);
  for (const q of quests) {
    const body = el("tbody", "quest-group");
    body.id = `quest-${q.id}`;
    const titleRow = el("tr", "quest-header");
    const title = el("th");
    title.scope = "row";
    title.append(el("span", "quest-title", q.title));
    const meta = el("div", "quest-meta");
    const level = q.level === -1 ? "Scales" : `Lvl ${q.level ?? "?"}`;
    meta.append(document.createTextNode(`${level} · #${q.id} · `),
      el("span", q.shared ? "shared" : "", q.shared ? `Shared by ${q.participants}` : "Solo quest"));
    if (!q.template_found) meta.append(document.createTextNode(" · Definition unavailable"));
    title.append(meta);
    titleRow.append(title);
    q.progress.forEach((p, index) => {
      const td = el("td", data.characters[index].name === state.selected ? "selected-column" : "");
      td.append(statusBadge(p));
      titleRow.append(td);
    });
    body.append(titleRow);
    for (const o of q.objectives) {
      const tr = el("tr", "objective-row");
      const th = el("th");
      th.scope = "row";
      const label = el("span", "objective-label");
      const icon = el("span", "objective-kind", icons[o.kind] || "◇");
      icon.setAttribute("aria-hidden", "true");
      label.append(icon, document.createTextNode(o.label));
      th.append(label);
      th.title = o.note || `${o.kind} objective`;
      tr.append(th);
      q.progress.forEach((p, index) => tr.append(objectiveCell(p, o, data.characters[index].name === state.selected)));
      body.append(tr);
    }
    table.append(body);
  }
  wrap.replaceChildren(table);
  wrap.scrollLeft = scrollLeft;
  wrap.scrollTop = scrollTop;
}

function focusQuest(id) {
  state.filter = "all";
  state.search = "";
  $("search").value = "";
  syncFilterButtons();
  renderTable(view());
  const row = $(`quest-${id}`);
  if (row) {
    row.classList.add("highlight");
    row.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
  }
}

function renderJournal(data) {
  const index = data.characters.findIndex((c) => c.name === state.selected);
  const c = data.characters[index];
  if (!c) {
    const empty = el("p", "empty-state", "Add a character to your watch list to see their journal.");
    $("journal-content").replaceChildren(empty);
    return;
  }
  const person = el("div", `journal-person ${className(c)}`);
  person.append(characterHead(c));
  person.append(el("p", "journal-sub", c.found ? `${c.active} quests · ${c.ready} ready · ${c.behind} catch-up entries`
    : "This name was not found in the saved character list."));
  if (state.view === "bots" && c.found) {
    person.append(el("p", "journal-xp", `Saved experience: ${c.xp.toLocaleString()} XP toward the next level`));
  }
  if (c.found) {
    const armory = el("a", "page-switch", "Equipment →");
    armory.href = "/armory?name=" + encodeURIComponent(c.name);
    const actions = el("div", "journal-actions");
    const journal = el("a", "page-switch", "Quest log →");
    journal.href = "/quest-log?name=" + encodeURIComponent(c.name);
    const inventory = el("a", "page-switch", "Inventory →");
    inventory.href = "/inventory?name=" + encodeURIComponent(c.name);
    actions.append(armory, inventory, journal); person.append(actions);
  }
  const list = el("ul", "journal-list");
  const quests = data.quests.filter((q) => ["active", "ready", "failed"].includes(q.progress[index].status));
  for (const q of quests) {
    const p = q.progress[index];
    const li = el("li");
    const button = el("button", "journal-quest");
    button.type = "button";
    button.addEventListener("click", () => focusQuest(q.id));
    button.append(el("span", "journal-quest-title", q.title));
    const meta = el("span", "journal-quest-meta");
    meta.append(el("span", p.status, labels[p.status]));
    const numeric = q.objectives.filter((o) => p.counts[o.key] !== null && p.counts[o.key] !== undefined);
    const complete = numeric.filter((o) => p.counts[o.key] >= o.required).length;
    meta.append(el("span", "", numeric.length ? `${complete}/${numeric.length} objectives` : "Status only"));
    button.append(meta, el("span", "journal-quest-description", q.description));
    li.append(button);
    list.append(li);
  }
  if (!quests.length) {
    const message = c.quest_state_available === false ? "Offline: no live quest state is available."
      : (c.found ? "No active quests in this observation." : "No data available.");
    list.append(el("li", "empty-state", message));
  }
  $("journal-content").replaceChildren(person, list);
}

function render() {
  const data = view();
  if (!data) return;
  $("bot-tools").hidden = state.view !== "bots";
  const source = state.snapshot.source;
  if (source) {
    $("source-tag").textContent = source.label;
    $("source-note").textContent = source.live
      ? "Live world-server observation. Offline characters have no live quest state; no saved snapshot is substituted."
      : "Saved MySQL snapshots. Characters save every 15 minutes; refreshing cannot reveal unsaved gameplay."
        + " The actual character save time is unknown.";
  }
  state.groups = state.snapshot.groups || state.groups;
  renderGroups();
  state.watched = state.snapshot.views.bots.characters.map((c) => c.name);
  const selectedBefore = $("bot-detail").value;
  $("bot-detail").replaceChildren(...state.watched.map((name) => {
    const option = el("option", "", name);
    option.value = name;
    return option;
  }));
  $("bot-detail").value = state.view === "bots" ? state.selected : selectedBefore;
  $("remove-bot").disabled = !state.watched.length;
  const focused = document.activeElement.id;
  if (!data.characters.some((c) => c.name === state.selected)) state.selected = data.characters[0]?.name;
  renderRoster(data);
  for (const key of ["active", "shared", "ready", "behind"]) $("stat-" + key).textContent = data.summary[key];
  renderTable(data);
  renderJournal(data);
  renderChangeStatus();
  renderAssistant(data);
  if (state.view === "bots") $("bot-detail").value = state.selected || "";
  if (focused && $(focused) && document.activeElement.id !== focused) $(focused).focus({ preventScroll: true });
}

function syncFilterButtons() {
  document.querySelectorAll(".filter").forEach((button) => {
    const selected = state.filter === button.dataset.filter;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}

function setView(name) {
  state.view = name;
  $("bot-tools").hidden = name !== "bots";
  state.selected = view()?.characters[0]?.name || null;
  ["party", "bots"].forEach((v) => {
    $(v + "-tab").classList.toggle("active", name === v);
    $(v + "-tab").setAttribute("aria-pressed", String(name === v));
  });
  state.filter = "all";
  state.search = "";
  $("search").value = "";
  syncFilterButtons();
  render();
}

function renderChangeStatus() {
  const changes = state.snapshot?.changes?.[state.view];
  $("change-status").textContent = changes?.last_observed_change_at
    ? "Last observed data change: " + new Date(changes.last_observed_change_at).toLocaleString()
    : "Last observed data change: none since monitoring began";
  $("change-status").title = "Compared with the previous successful snapshot in this dashboard process. This is an observation time, not a server save timestamp. Changing the watch list resets the baseline.";
}
function renderStatus() {
  const status = $("refresh-status");
  status.classList.toggle("stale", Boolean(state.error));
  const label = state.lastSuccess ? `Last successful refresh: ${new Date(state.lastSuccess).toLocaleString()}`
    : "No successful refresh yet";
  status.replaceChildren(el("span", "dot"), document.createTextNode(label));
  $("error").hidden = !state.error;
  const fallback = state.snapshot ? "Showing the last successful snapshot." : "";
  $("error").textContent = state.error ? `${state.error} ${fallback}` : "";
}

function schedule() {
  clearTimeout(state.timer);
  const seconds = Number($("interval").value);
  if (seconds && !document.hidden) state.timer = setTimeout(refresh, seconds * 1000);
}

async function refresh(groupRefresh = false) {
  if (state.busy || (state.groupBusy && groupRefresh !== true)) return;
  clearTimeout(state.timer);
  state.busy = true;
  $("refresh").disabled = true;
  lockGroupControls();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch("/api/snapshot", { cache: "no-store", signal: controller.signal });
    const data = await response.json();
    if (data.snapshot) {
      state.snapshot = data.snapshot;
      state.lastSuccess = data.snapshot.last_success;
      render();
    }
    state.error = data.ok && response.ok ? null : (data.error || "The database snapshot could not be refreshed.");
  } catch {
    state.error = "Cannot reach the local dashboard. Check that its Python process is running.";
  } finally {
    clearTimeout(timeout);
    state.busy = false;
    $("refresh").disabled = false;
    lockGroupControls();
    renderStatus();
    schedule();
  }
}

$("refresh").addEventListener("click", refresh);
$("interval").addEventListener("change", schedule);
$("party-tab").addEventListener("click", () => setView("party"));
$("bots-tab").addEventListener("click", () => setView("bots"));
document.querySelectorAll(".filter").forEach((button) => button.addEventListener("click", () => {
  state.filter = button.dataset.filter;
  syncFilterButtons();
  if (view()) renderTable(view());
}));
$("search").addEventListener("input", (event) => {
  state.search = event.target.value.trim().toLocaleLowerCase();
  if (view()) renderTable(view());
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearTimeout(state.timer);
  else refresh();
});
async function loadSession() {
  const response = await fetch("/api/session", { cache: "no-store" });
  const data = await response.json();
  state.token = data.token;
  state.watched = data.bots;
  state.notes = data.notes || {};
  state.noteImages = data.note_images || {};
  state.groups = data.groups;
  renderGroups();
}

async function saveWatchList(names, selected) {
  $("add-bot").disabled = true;
  try {
    if (!state.token) await loadSession();
    const response = await fetch("/api/watchlist", { method: "POST", headers: {
      "Content-Type": "application/json", "X-Dashboard-Token": state.token }, body: JSON.stringify({ names }) });
    const result = await response.json();
    if (!result.ok) throw new Error(result.error);
    state.watched = result.names;
    state.selected = selected || result.names[0];
    $("bot-name").value = "";
    $("watch-status").textContent = "Watch list saved. Select a card or the journal menu to inspect a bot.";
    await refresh();
  } catch (error) {
    $("watch-status").textContent = error.message || "Could not update the watch list.";
  } finally {
    $("add-bot").disabled = false;
  }
}

$("add-bot").addEventListener("click", () => {
  const value = $("bot-name").value.trim();
  if (!/^[A-Za-z]{2,12}$/.test(value)) {
    $("watch-status").textContent = "Enter a character name using 2–12 letters.";
    return;
  }
  const name = value[0].toUpperCase() + value.slice(1).toLowerCase();
  saveWatchList([...state.watched, name], name);
});
$("remove-bot").addEventListener("click", () => saveWatchList(
  state.watched.filter((name) => name !== state.selected)));
$("bot-detail").addEventListener("change", () => selectCharacter($("bot-detail").value));
$("bot-name").addEventListener("keydown", (event) => {
  if (event.key === "Enter") { event.preventDefault(); $("add-bot").click(); }
});
let searchTimer;
$("bot-name").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    const term = $("bot-name").value.trim();
    if (!/^[A-Za-z]{0,12}$/.test(term)) return;
    try {
      const response = await fetch("/api/characters?q=" + encodeURIComponent(term));
      const data = await response.json();
      $("bot-suggestions").replaceChildren(...(data.characters || []).map((row) => {
        const option = el("option", "", `Level ${row[1]} · ${row[3] === "1" ? "Online" : "Offline"}`);
        option.value = row[0];
        return option;
      }));
    } catch { /* Search is optional; adding a valid name still works. */ }
  }, 250);
});
function lockGroupControls() {
  const disabled = state.busy || state.groupBusy || !state.groups;
  document.querySelectorAll('.group-tools button, .group-tools input, .group-tools select').forEach(n => { n.disabled = disabled; });
  if (!disabled) {
    $('group-delete').disabled = state.groups.groups.length <= 1;
    $('group-edit').disabled = !state.groups.groups.length;
    $('group-select').disabled = !state.groups.groups.length;
  }
}
function renderGroups() {
  if (!state.groups) return;
  $('group-select').replaceChildren(...state.groups.groups.map(group => {
    const option = el('option', '', `${group.name} (${group.members.length})`);
    option.value = group.id; return option;
  }));
  $('group-select').value = state.groups.selected;
  const selected = state.groups.groups.find(g => g.id === state.groups.selected);
  $('party-tab').replaceChildren(document.createTextNode((selected?.name || 'Your group') + ' '), el('span', '', selected?.members.length || 0));
  if(!selected){$('group-editor').open=true;$('group-status').textContent='Create your first group with 1–10 character names to get started.';}
  lockGroupControls();
}
function editGroup(group = null) {
  state.editingGroup = group?.id || null;
  $('group-editor-title').textContent = group ? 'Edit group' : 'Create a group';
  $('group-save').textContent = group ? 'Save group' : 'Create group';
  $('group-name').value = group?.name || '';
  document.querySelectorAll('#group-members input').forEach((input,i) => { input.value = group?.members[i] || ''; });
}
async function changeGroup(payload) {
  if (state.busy || state.groupBusy) return;
  state.groupBusy = true; lockGroupControls();
  try {
    if (!state.token) await loadSession();
    const response = await fetch('/api/groups', {method: 'POST', headers: {
      'Content-Type': 'application/json', 'X-Dashboard-Token': state.token}, body: JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Could not save the group.');
    state.groups = result.groups;
    // Never show a previous group's comparison under the newly selected group name.
    state.snapshot = null; state.selected = null; state.lastSuccess = null;
    clearAssistant();
    $("change-status").textContent = ""; $("quest-count").textContent = "— quests";
    $('roster').replaceChildren(el('div', 'loading-card', 'Loading the selected group…'));
    $('table-wrap').replaceChildren(el('p', 'empty-state', 'Loading the selected group…'));
    $('journal-content').replaceChildren();
    for (const key of ['active', 'shared', 'ready', 'behind']) $('stat-' + key).textContent = '—';
    renderGroups();
    editGroup();
    setView('party');
    $('group-status').textContent = 'Group saved. The selected group will open next time.';
    await refresh(true);
  } catch (error) {
    $('group-status').textContent = error.message || 'Could not save the group.';
    renderGroups();
  } finally { state.groupBusy = false; lockGroupControls(); }
}
for (let i = 0; i < 10; i++) {
  const label = el('label', '', `Character ${i + 1}`), input = el('input');
  input.id = 'group-member-' + i; input.maxLength = 12;
  input.pattern = '[A-Za-z]{2,12}'; input.autocomplete = 'off'; input.setAttribute('list', 'group-suggestions');
  label.append(input); $('group-members').append(label);
  let timer;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    const term = input.value.trim();
    if (!/^[A-Za-z]{0,12}$/.test(term)) return;
    timer = setTimeout(async () => {
      try {
        const response = await fetch('/api/characters?q=' + encodeURIComponent(term));
        const result = await response.json();
        if (input.value.trim() !== term) return;
        $('group-suggestions').replaceChildren(...(result.characters || []).map(row => {
          const option = el('option'); option.value = row[0]; return option;
        }));
      } catch { /* Valid names can still be entered if suggestions are unavailable. */ }
    }, 250);
  });
}
$('group-select').addEventListener('change', () => changeGroup({action: 'select', id: $('group-select').value}));
$('group-new').addEventListener('click', () => { editGroup(); $('group-name').focus(); });
$('group-edit').addEventListener('click', () => editGroup(state.groups.groups.find(g => g.id === state.groups.selected)));
$('group-delete').addEventListener('click', () => {
  if (state.busy || state.groupBusy || !state.groups || state.groups.groups.length <= 1) return;
  const group = state.groups.groups.find(g => g.id === state.groups.selected);
  if (!group || !window.confirm(`Delete the group “${group.name}”? This cannot be undone. Character data will be kept.`)) return;
  changeGroup({action: 'delete', id: group.id});
});
$('group-form').addEventListener('submit', event => {
  event.preventDefault();
  const members = [...document.querySelectorAll('#group-members input')].map(n => n.value.trim()).filter(Boolean);
  changeGroup({action: state.editingGroup ? 'edit' : 'create', id: state.editingGroup, name: $('group-name').value.trim(), members});
});
let assistantKey = null, activityOffset = 0, activityRequest = 0, activityController = null;
function clearAssistant() {
  assistantKey = null; ++activityRequest; activityController?.abort(); $('party-assistant').hidden = true;
}
function questLink(id, title, name = '') {
  const a = el('a', '', title); a.href = '/quest-log?mode=all&q=' + id + '&id=' + id;
  if (name) a.href = '/quest-log?name=' + encodeURIComponent(name) + '&q=' + id + '&id=' + id;
  const links=el('span');const external=wowheadLink('↗','quest',id);external.classList.add('wowhead-shortcut');external.setAttribute('aria-label','View '+title+' on Wowhead');links.append(a,external);return links;
}
function renderAssistant(data) {
  const key = state.view + ':' + state.snapshot.last_success;
  if (key === assistantKey) return;
  assistantKey = key; ++activityRequest; activityController?.abort();
  const planning = data.planning;
  if (!planning) { $('party-assistant').hidden = true; return; }
  $('party-assistant').hidden = false;
  $('planning-warning').textContent = [planning.warning,data.activity?.warning].filter(Boolean).join(' ');
  const actionNode = action => {
    const li = el('li'); li.append(questLink(action.quest, action.text));
    li.append(el('p','assistant-members',action.characters.join(', ')),el('p','assistant-reason',action.reason)); return li;
  };
  $('next-actions').replaceChildren(...planning.actions.slice(0,6).map(actionNode));
  if (!planning.actions.length) $('next-actions').append(el('li','assistant-reason','No actionable saved quests for this group.'));
  $('remaining-actions').replaceChildren(...planning.actions.slice(6).map(actionNode));
  $('more-actions').hidden = planning.actions.length <= 6;
  const selectedStart = $('route-start').value;
  $('route-start').replaceChildren(...(planning.starts.length ? planning.starts.map(c => {
    const option = el('option','',c.name); option.value = String(c.guid); return option;
  }) : [el('option','','Position unavailable')]));
  if (!planning.starts.length) $('route-start').firstChild.value = 'unknown';
  if ([...$('route-start').options].some(o => o.value === selectedStart)) $('route-start').value = selectedStart;
  $('route-note').textContent = 'Nearby work is grouped within about 1,000 world units. Stops use a straight-line nearest-neighbour order from the saved position; this is not a fastest or navigable route. ' + planning.location_note;
  renderStops();
  $('unknown-stops').replaceChildren(...planning.unknown_locations.map(item => el('p','assistant-reason',
    `${item.title} · ${item.characters.join(', ')}: ${item.role === 'handin' ? 'hand-in' : 'objective'} location unknown. Journal category: ${item.category}; this does not establish where the activity happens.`)));
  $('quest-locations').replaceChildren(...data.quests.map(q => {
    const div = el('div','location-entry'); div.append(questLink(q.id,q.title),el('p','assistant-reason','Journal category: '+q.zone));
    if (!q.locations.length) div.append(el('p','assistant-reason','Objective and contact locations are unavailable.'));
    for (const loc of q.locations){const p=el('p','assistant-reason',`${loc.role === 'handin' ? 'Hand-in' : loc.role === 'start' ? 'Accept' : 'Objective'} · `);p.append(wowheadLink(loc.name,loc.entity_type,loc.entity_id),document.createTextNode(` · ${loc.zone} · ${loc.map_name} · world ${Math.round(loc.x)}, ${Math.round(loc.y)} · ${loc.source}${loc.rank >= (loc.approximate ? 13 : 7) ? ' · source display limit reached' : ''}`));div.append(p);}
    return div;
  }));
  const reasons = [];
  for (const q of data.quests) q.progress.forEach((p,i) => {
    if (!p.explanation) return;
    const entry = el('div','missing-entry'); entry.append(questLink(q.id,q.title),el('span','confidence-pill '+p.explanation.confidence,p.explanation.confidence));
    entry.append(el('p','assistant-members',`${data.characters[i].name} · ${p.explanation.label}`));
    entry.append(el('p','assistant-reason',p.explanation.reasons.join(' '))); reasons.push(entry);
  });
  $('missing-reasons').replaceChildren(...(reasons.length ? reasons : [el('p','assistant-reason','No missing quest comparisons for this group.')]));
  const previousCharacter = $('activity-character').value;
  $('activity-character').replaceChildren(el('option','','All displayed characters'), ...data.characters.map(c => {
    const option = el('option','',c.name); option.value = c.name; return option;
  }));
  $('activity-character').firstChild.value = '';
  if ([...$('activity-character').options].some(o=>o.value===previousCharacter)) $('activity-character').value = previousCharacter;
  $('activity-section').querySelector('summary').textContent = 'Activity history' + (data.activity?.total ? ' · '+data.activity.total+' retained' : '');
  activityOffset = 0;
  if ($('activity-character').value || $('activity-kind').value) loadActivity();
  else renderActivity(data.activity || {events:[],total:0});
}
function renderStops() {
  const planning = view()?.planning; if (!planning) return;
  const stops = planning.routes[$('route-start').value] || [];
  $('route-stops').replaceChildren(...stops.map(stop => {
    const li = el('li'); li.append(el('h3','',stop.zone+' · '+stop.map_name));
    li.append(el('p','assistant-reason',`Approximate stop near world ${Math.round(stop.x)}, ${Math.round(stop.y)}. Check each contact or search area before travelling.`));
    const list = el('ul');
    for (const item of stop.activities) {
      const row = el('li'); row.append(questLink(item.quest,item.task));
      row.append(el('p','assistant-members',item.characters.join(', ')));
      const reason=el('p','assistant-reason',item.objective_label ? item.objective_label+' · ' : '');reason.append(wowheadLink(item.name,item.entity_type,item.entity_id),document.createTextNode(` · ${item.source}${item.alternative ? ' · one candidate chosen from alternatives' : ''}`));row.append(reason);list.append(row);
    }li.append(list);return li;
  }));
  if (!stops.length) $('route-stops').append(el('li','assistant-reason','No candidate locations are available for suggested stops.'));
}
function renderActivity(result) {
  const events = result.events || [], total = result.total || 0;
  $('activity-status').textContent = result.warning || (total ? `${total} retained observations for these filters. Newest first; up to 5,000 observations retained across monitored characters.` : 'No changes observed yet. The first successful read establishes a baseline.');
  $('activity-events').replaceChildren(...events.map(event => {
    const li = el('li'); li.append(el('strong','',event.name+' · '+event.message));
    if (event.quest) li.append(document.createTextNode(' · '),questLink(event.quest,event.title || 'Quest #'+event.quest));
    const time = el('time','', 'First observed: '+new Date(event.observed).toLocaleString()); time.dateTime = event.observed;
    time.title = 'Previous successful observation: '+new Date(event.previous_observed).toLocaleString(); li.append(time); return li;
  }));
  $('activity-page').textContent = total ? `${activityOffset+1}–${Math.min(activityOffset+events.length,total)} of ${total}` : '0 observations';
  $('activity-newer').disabled = activityOffset === 0; $('activity-older').disabled = activityOffset+50 >= total;
}
async function loadActivity() {
  const request = ++activityRequest, key = assistantKey; activityController?.abort();
  const controller = new AbortController(); activityController = controller;
  const timeout = setTimeout(()=>controller.abort(),10000);
  $('activity-newer').disabled = true; $('activity-older').disabled = true;
  $('activity-status').textContent = 'Loading observed activity…';
  try {
    const params = new URLSearchParams({view:state.view,character:$('activity-character').value,kind:$('activity-kind').value,offset:activityOffset});
    const response = await fetch('/api/activity?'+params,{cache:'no-store',signal:controller.signal}); const result = await response.json();
    if (request !== activityRequest || key !== assistantKey) return;
    if (!response.ok || !result.ok) throw new Error(result.error || 'Activity unavailable.');
    renderActivity(result.activity);
  } catch (error) { if (request === activityRequest && key === assistantKey) {
    $('activity-status').textContent = error.name === 'AbortError' ? 'Activity request timed out. Refresh or change a filter to retry.' : error.message;
    $('activity-events').replaceChildren();
  }} finally { clearTimeout(timeout); }
}
$('route-start').addEventListener('change',renderStops);
for (const id of ['activity-character','activity-kind']) $(id).addEventListener('change',()=>{activityOffset=0;loadActivity();});
$('activity-newer').addEventListener('click',()=>{activityOffset=Math.max(0,activityOffset-50);loadActivity();});
$('activity-older').addEventListener('click',()=>{activityOffset+=50;loadActivity();});
let watchNoteName = null, watchNoteBusy = false;
let watchNoteImageFile = null, watchNoteImageRemoved = false, watchNoteImageURL = null;
function noteFor(name) { return state.notes[name[0].toUpperCase()+name.slice(1).toLowerCase()] || ''; }
function noteImageFor(name) { return state.noteImages[name[0].toUpperCase()+name.slice(1).toLowerCase()] || null; }
function clearNoteImageURL() {
  if(watchNoteImageURL)URL.revokeObjectURL(watchNoteImageURL);
  watchNoteImageURL=null;
}
function renderNoteImage() {
  const saved=noteImageFor(watchNoteName),file=watchNoteImageFile;
  const shown=file||(!watchNoteImageRemoved&&saved);
  $('watch-note-image-preview').hidden=!shown;
  if(!shown){$('watch-note-image-preview-img').removeAttribute('src');$('watch-note-image-view').removeAttribute('href');return;}
  const url=file?watchNoteImageURL:saved.url;
  $('watch-note-image-preview-img').src=url;
  $('watch-note-image-view').href=url;
  $('watch-note-image-name').textContent=file?file.name:saved.name;
}
function readNoteImage(file) {
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onload=()=>resolve({name:file.name.slice(0,160),data:reader.result.split(',')[1]});
    reader.onerror=()=>reject(new Error('Cannot read this image. Choose it again and retry.'));
    reader.onabort=()=>reject(new Error('Reading the image was cancelled.'));
    reader.readAsDataURL(file);
  });
}
$('watch-note-image').addEventListener('change',()=>{
  const files=$('watch-note-image').files;
  if(!files.length)return;
  if(files.length!==1||!['image/png','image/jpeg'].includes(files[0].type)||files[0].size>5*1024*1024){
    $('watch-note-status').textContent='Choose one PNG or JPEG image, up to 5 MiB.';
    $('watch-note-image').value='';return;
  }
  clearNoteImageURL();watchNoteImageFile=files[0];watchNoteImageRemoved=false;
  watchNoteImageURL=URL.createObjectURL(watchNoteImageFile);
  $('watch-note-status').textContent='Image ready. Save the note to attach it.';renderNoteImage();
});
$('watch-note-image-remove').addEventListener('click',()=>{
  clearNoteImageURL();watchNoteImageFile=null;watchNoteImageRemoved=true;$('watch-note-image').value='';
  $('watch-note-status').textContent='Image removed from this draft. Save to apply.';renderNoteImage();
});
function noteCount() { $('watch-note-count').textContent = $('watch-note-text').value.length.toLocaleString()+' / 2,000 characters'; }
function openWatchNote(character) {
  watchNoteName = character.name;
  clearNoteImageURL();watchNoteImageFile=null;watchNoteImageRemoved=false;$('watch-note-image').value='';renderNoteImage();
  $('watch-note-title').textContent = 'Note for '+character.name;
  $('watch-note-context').textContent = character.found ? `Current saved level ${character.level} ${character.class_name}. Record the level and location you first saw them in your own words.` : 'This name is not in the current saved character data. Your note can still be saved.';
  $('watch-note-text').value = noteFor(character.name);
  $('watch-note-status').textContent = ''; noteCount();
  $('watch-note-dialog').showModal(); $('watch-note-text').focus();
}
$('watch-note-text').addEventListener('input',noteCount);
$('watch-note-clear').addEventListener('click',()=>{ $('watch-note-text').value='';noteCount();$('watch-note-text').focus(); });
$('watch-note-cancel').addEventListener('click',()=>{ if(!watchNoteBusy)$('watch-note-dialog').close(); });
$('watch-note-dialog').addEventListener('cancel',event=>{ if(watchNoteBusy)event.preventDefault(); });
$('watch-note-dialog').addEventListener('close',()=>{
  clearNoteImageURL();watchNoteImageFile=null;watchNoteImageRemoved=false;
  [...document.querySelectorAll('[data-note-name]')].find(button=>button.dataset.noteName===watchNoteName)?.focus({preventScroll:true});
});
$('watch-note-form').addEventListener('submit',async event=>{
  event.preventDefault(); if(watchNoteBusy)return;
  watchNoteBusy=true;
  const name=watchNoteName,text=$('watch-note-text').value;
  const controls=[$('watch-note-save'),$('watch-note-cancel'),$('watch-note-clear'),$('watch-note-text'),$('watch-note-image'),$('watch-note-image-remove')];
  controls.forEach(n=>n.disabled=true);$('watch-note-status').textContent='Saving…';
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
  try {
    if(!state.token)await loadSession();
    const payload={name,text};
    if(watchNoteImageFile)payload.image=await readNoteImage(watchNoteImageFile);
    else if(watchNoteImageRemoved)payload.image=null;
    const response=await fetch('/api/watch-notes',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':state.token},
      body:JSON.stringify(payload),signal:controller.signal});
    const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||'Could not save this note.');
    if(result.note.text||result.note.image)state.notes[result.note.name]=result.note.text;else delete state.notes[result.note.name];
    if(Object.hasOwn(result.note,'image')){if(result.note.image)state.noteImages[result.note.name]=result.note.image;else delete state.noteImages[result.note.name];}
    if(view())renderRoster(view());
    $('watch-note-dialog').close();
    $('watch-status').textContent=result.note.text||result.note.image?'Note saved for '+result.note.name+'.':'Note cleared for '+result.note.name+'.';
  } catch(error) {
    $('watch-note-status').textContent=error.name==='AbortError'?'Saving timed out. Your note and image draft are still here; retry or cancel.':(error.message||'Could not save this note. Your note and image draft are still here.');
  } finally {clearTimeout(timeout);watchNoteBusy=false;controls.forEach(n=>n.disabled=false);}
});
loadSession().catch(() => {}).finally(refresh);

async function loadServerIdentity() {
  const label = document.getElementById('server-identity');
  try {
    const response = await fetch('/api/server-identity', {cache: 'no-store'});
    if (!response.ok) throw new Error('Identity unavailable');
    const data = await response.json();
    label.textContent = `${data.realm} · Host: ${data.host}`;
  } catch (_) {
    label.textContent = 'Realm / host unavailable';
  }
}
loadServerIdentity();
setInterval(() => { if (!document.hidden) loadServerIdentity(); }, 60000);
