# Maintaining this dashboard

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
