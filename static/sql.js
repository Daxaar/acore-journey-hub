"use strict";
const $ = (id) => document.getElementById(id);
let token, tables = [], policy = null;
const examples = {
  characters: "SELECT name, level, class, online\nFROM acore_characters.characters\n"
    + "WHERE name IN ('Yourcharacter','Yourfriend')\nORDER BY name;",
  quests: "SELECT c.name, s.quest, q.LogTitle, s.status, s.mobcount1, s.itemcount1, s.explored\n"
    + "FROM acore_characters.characters c\nJOIN acore_characters.character_queststatus s ON s.guid = c.guid\n"
    + "JOIN acore_world.quest_template q ON q.ID = s.quest\n"
    + "WHERE c.name = 'Yourcharacter' AND s.status IN (1,3,5)\nORDER BY s.quest;",
  shared: "SELECT s.quest, q.LogTitle, COUNT(*) AS participants\n"
    + "FROM acore_characters.character_queststatus s\n"
    + "JOIN acore_characters.characters c ON c.guid = s.guid\n"
    + "JOIN acore_world.quest_template q ON q.ID = s.quest\n"
    + "WHERE c.name IN ('Yourcharacter','Yourfriend') AND s.status IN (1,3,5)\n"
    + "GROUP BY s.quest, q.LogTitle\nHAVING COUNT(*) > 1\nORDER BY participants DESC;"
};
function node(tag, text) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = String(text);
  return element;
}
function showCatalog() {
  const term = $("table-search").value.toLowerCase();
  const schema = $("sql-schema").value;
  const entries = tables.filter(([db, name]) => db === schema && name.toLowerCase().includes(term));
  $("sql-tables").replaceChildren(...entries.map(([db, name]) => {
    const button = node("button", name);
    button.addEventListener("click", () => {
      $("sql-query").value = `SELECT *\nFROM ${db}.${name}\nLIMIT 50;`;
      $("sql-query").focus();
    });
    return button;
  }));
}
async function run() {
  $("sql-run").disabled = true;
  $("sql-status").textContent = "Running a bounded, read-only SELECT…";
  try {
    const response = await fetch("/api/sql/query", { method: "POST", headers: {
      "Content-Type": "application/json", "X-Dashboard-Token": token },
      body: JSON.stringify({ schema: $("sql-schema").value, query: $("sql-query").value }) });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error);
    const result = data.result;
    renderPolicy(result.policy);
    const table = node("table");
    const header = node("tr");
    result.columns.forEach((name) => header.append(node("th", name)));
    const head = node("thead"); head.append(header); table.append(head);
    const body = node("tbody");
    result.rows.forEach((row) => {
      const tr = node("tr");
      row.forEach((value) => tr.append(node("td", value === null ? "NULL" : value)));
      body.append(tr);
    });
    table.append(body);
    $("sql-results").replaceChildren(result.rows.length ? table : node("p", "No matching rows."));
    $("sql-result-meta").textContent = `${result.rows.length} rows · ${result.duration_ms} ms`;
    $("sql-status").textContent = result.truncated
      ? "Showing the first 200 rows. Narrow your WHERE clause to explore more."
      : "Query completed. The database was not changed.";
  } catch (error) {
    $("sql-status").textContent = error.message || "Could not reach the dashboard. Reload and try again.";
    $("sql-results").replaceChildren(node("p", "Query was not completed. Previous results have been cleared."));
    $("sql-result-meta").textContent = "No result";
  } finally { $("sql-run").disabled = false; }
}
$("sql-query").value = examples.characters;
$("sql-run").disabled = true;
$("sql-run").addEventListener("click", run);
$("sql-example").addEventListener("change", () => { $("sql-query").value = examples[$("sql-example").value]; });
$("sql-schema").addEventListener("change", showCatalog);
$("table-search").addEventListener("input", showCatalog);
$("sql-query").addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.key === "Enter" && !$("sql-run").disabled) { event.preventDefault(); run(); }
});
Promise.all([fetch("/api/session").then((r) => r.json()), fetch("/api/sql/catalog").then((r) => r.json())])
  .then(([session, catalog]) => {
    if (!catalog.ok) throw new Error(catalog.error);
    token = session.token;
    tables = catalog.tables;
    showCatalog();
    $("sql-status").textContent = `${tables.length} tables/views available. Ready for your SELECT.`;
    $("sql-run").disabled = false;
  }).catch((error) => { $("sql-status").textContent = error.message || "Could not load the database catalog."; });

function renderPolicy(next) {
  if (!next) return;
  policy = next;
  const rows = next.row_limit ? "200 rows" : "No automatic row cap";
  const duration = next.execution_timeout ? "3-second execution limit" : "No query deadline";
  const catalog = next.base_tables_only ? "base tables only" : "tables and views";
  $("sql-policy").textContent = `${rows} · ${duration} · ${catalog}.`;
}
window.dashboardSettingsReady.then((settings) => renderPolicy(settings.sql)).catch(() => {});
window.addEventListener("dashboard-settings", async (event) => {
  const next = event.detail.sql;
  const reload = policy && policy.base_tables_only !== next.base_tables_only;
  renderPolicy(next);
  if (reload) {
    try {
      const response = await fetch("/api/sql/catalog", { cache: "no-store" });
      const result = await response.json();
      if (result.ok) { tables = result.tables; showCatalog(); }
    } catch { /* Reloading the page retries catalog loading. */ }
  }
});
