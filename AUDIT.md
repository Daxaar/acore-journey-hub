# Refactoring audit

Application branding appeared in page titles, navigation headers, HTTP identity, the startup message, browser component names and release filenames. These now use Journey Hub. The historical browser appearance storage key and legacy LEMMINGS_* environment aliases remain deliberately compatible; they do not seed characters or records.

Groups, selected members, GUIDs, accounts, guild membership and inventory are data driven. Groups support 1–10 characters, up to 32 saved groups and 32 watched characters; these are documented bounds, not a fixed five-character roster. Guild-specific deployment discovery was replaced by a requested group name with an optional guild filter. No guild is required.

Docker defaults were installation-specific; generic defaults are now database/worldserver, with explicit local configuration or environment overrides. Database schema mapping, direct TCP MySQL credentials and DBC paths are configurable. Legacy Docker mode still uses the container's root credential internally; SELECT-only direct credentials are recommended. No server/database migration is included.

Persistent state: groups.json, watchlist.json, watch-notes.json, settings.json, client-models.json, network.json, deployment.json, gear-planner.json; activity.sqlite3; independent journal.sqlite3 (including screenshot bytes); retained legacy crafting-reviews.sqlite3 (unused); generated assets/. Logs, virtual environments and caches are local. None is copied to the new application or public archive.

Game access: SELECT queries, metadata reads and read-only transactions. Local writes: dashboard settings, rosters, notes, role choices, activity observations, journal records/screenshots. Asset preparation writes local caches only. Optional live API access is HTTP read access. Docker commands inspect/read existing containers; they never create or restart game services.

Development uses a separate allowlisted source copy. The live installation remains in place. Before editing, source/configuration were backed up privately and each existing SQLite database was captured using sqlite3.Connection.backup. No game records, private configuration, logs, generated caches or historical screenshots are release inputs. Synthetic test character names were generalised too.
