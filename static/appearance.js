"use strict";

(() => {
  const themes = ["forest", "frost", "crimson", "arcane", "parchment"];
  const fonts = ["classic", "modern", "bookish", "monospace"];
  const cacheKey = "lemmings-dashboard-settings-v1";
  function preview(appearance) {
    if (themes.includes(appearance?.theme)) document.documentElement.dataset.theme = appearance.theme;
    if (fonts.includes(appearance?.font)) document.documentElement.dataset.font = appearance.font;
  }
  function publish(settings, persist = true) {
    window.dashboardSettings = settings;
    preview(settings.appearance);
    if (persist) {
      try { localStorage.setItem(cacheKey, JSON.stringify(settings)); } catch { /* Storage is optional. */ }
    }
    window.dispatchEvent(new CustomEvent("dashboard-settings", { detail: settings }));
  }
  try { preview(JSON.parse(localStorage.getItem(cacheKey))?.appearance); } catch { /* Default theme. */ }
  window.CharacterHubAppearance = { preview, publish };
  window.dashboardSettingsReady = fetch("/api/settings", { cache: "no-store" })
    .then((response) => response.json()).then((data) => {
      if (!data.ok) throw new Error("Could not load saved settings.");
      publish(data.settings);
      return data.settings;
    });
  // Other open tabs adopt a saved appearance and SQL policy label without needing a page reload.
  window.addEventListener("storage", (event) => {
    if (event.key === cacheKey && event.newValue) {
      try { publish(JSON.parse(event.newValue), false); } catch { /* Invalid cache is ignored. */ }
    }
  });
  window.dashboardSettingsReady.catch(() => {});
})();
