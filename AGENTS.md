# Maintaining this dashboard

- **Treat `character-hub-live` as ALWAYS read-only. Never create, edit, replace, delete, deploy,
  or otherwise change code, data, configuration, databases, assets or any other files in that folder.**
  Read existing files only to inspect or copy them into an isolated preview. Do not run the application,
  setup scripts, asset generators or package watchers from that folder, or point writable preview paths
  or symlinks into it. All development, generated artifacts and testing writes belong in the checkout
  or an isolated preview directory. The user manages live deployments themselves.

- Before editing, make a timestamped backup under `backups/`, excluding other backups, build output,
  caches and private tool directories. Capture every running SQLite database with its online backup API,
  including `activity.sqlite3` and the independent `journal.sqlite3` (stories and screenshots).
- Preserve existing local groups, watch lists, notes, settings, history and network/client configuration.
- New installations must have no seeded characters, groups or watched bots. Keep the empty-state setup usable.
- After every code or UI change, run appropriate checks and `python3 package_release.py`. Verify the clean
  public package has been regenerated before reporting completion. Include new source files in the builder's
  explicit allowlist as necessary. Never add local state, generated game assets, logs or backups to that list.
- The public installation guide is `PUBLIC_README.md`; packaging copies it to the release README.md.
- Do not publish or push to GitHub unless explicitly requested. Creating local release artifacts is authorized.
- Keep Gear Planner immediately after Armory & Bags in page navigation, and always keep Settings last when adding tabs.
- Link displayed game records with known types and IDs to their Wowhead WotLK pages; preserve dashboard detail actions and use the shared wowheadLink helper for new UI.
- Quest names should open the dashboard quest log in All Quests world-search mode, with a separate ↗ Wowhead link; use questLinks for new quest references.
- Keep tooltip text plain; database and dashboard links belong on the underlying page, not inside tooltips.

- After completing each change, run `.venv/bin/python preview.py` from the checkout (or `python3 preview.py`
  if no virtual environment exists). This rebuilds the clean package and starts/restarts the isolated test
  server at `http://localhost:8766`, using copies of configuration, groups, assets and online SQLite backups
  from the sibling `character-hub-live` installation. Use `--live /path/to/installation` if needed.
- Verify the preview responds before reporting completion and include a clickable link to the relevant
  preview page in the final response. Keep the preview running for the user to test. Never deploy changes
  into the live installation as part of this preview workflow. Preview state is disposable and is refreshed
  from live data on each run; do not copy preview changes back into live storage.
