"use strict";
const $ = (id) => document.getElementById(id);
const defaults = { sql: { base_tables_only: true, execution_timeout: true, row_limit: true },
  appearance: { theme: "forest", font: "classic" } };
let token;
function fill(settings) {
  $("theme").value = settings.appearance.theme;
  $("font").value = settings.appearance.font;
  $("base-tables").checked = settings.sql.base_tables_only;
  $("query-timeout").checked = settings.sql.execution_timeout;
  $("row-limit").checked = settings.sql.row_limit;
  window.JourneyHubAppearance.preview(settings.appearance);
}
function values() {
  return { sql: { base_tables_only: $("base-tables").checked, execution_timeout: $("query-timeout").checked,
    row_limit: $("row-limit").checked }, appearance: { theme: $("theme").value, font: $("font").value } };
}
$("settings-form").addEventListener("change", () => {
  window.JourneyHubAppearance.preview(values().appearance);
  $("settings-status").textContent = "Previewing your changes. Save settings to apply them.";
});
$("settings-reset").addEventListener("click", () => {
  fill(defaults);
  $("settings-status").textContent = "Defaults loaded. Save settings to restore them.";
});
$("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("settings-save").disabled = true;
  try {
    const response = await fetch("/api/settings", { method: "POST", headers: {
      "Content-Type": "application/json", "X-Dashboard-Token": token }, body: JSON.stringify(values()) });
    const result = await response.json();
    if (!result.ok) throw new Error(result.error);
    window.JourneyHubAppearance.publish(result.settings);
    $("settings-status").textContent = "Settings saved. New queries and pages will use these preferences.";
  } catch (error) {
    $("settings-status").textContent = error.message || "Cannot save settings. Reload and try again.";
  } finally { $("settings-save").disabled = false; }
});
Promise.all([window.dashboardSettingsReady, fetch("/api/session").then((response) => response.json())])
  .then(([settings, session]) => {
    token = session.token;
    fill(settings);
    $("settings-save").disabled = false;
    $("settings-status").textContent = "Ready. SQL limits are enabled by default; read-only access is permanent.";
  }).catch(() => { $("settings-status").textContent = "Cannot load settings. Check the dashboard and reload."; });

async function loadClientSettings() {
  try {
    const session = await (await fetch('/api/session')).json();
    const response = await fetch('/api/models/config');const result = await response.json();
    if (!result.ok) throw new Error('Client settings unavailable');
    $('models-enabled').checked = result.config.enabled;$('client-path').value = result.config.client_path;
    $('client-model-save').disabled = false;
    $('client-model-status').textContent = 'Ready. Model failures use the paper-doll automatically.';
    $('client-model-form').addEventListener('submit',async event => {
      event.preventDefault();$('client-model-save').disabled=true;
      try {
        const response=await fetch('/api/models/config',{method:'POST',headers:{'Content-Type':'application/json','X-Dashboard-Token':session.token},body:JSON.stringify({enabled:$('models-enabled').checked,client_path:$('client-path').value})});
        const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||'Cannot save client settings');
        $('client-model-status').textContent='Client settings saved. Reload the Armory to use the new path. Unavailable assets use the paper-doll.';
      } catch(error) {$('client-model-status').textContent=error.message;}
      finally {$('client-model-save').disabled=false;}
    });
  } catch (_) {$('client-model-status').textContent='Cannot load client settings. Reload to try again.';}
}
loadClientSettings();
