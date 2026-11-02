# Deployment and maintenance

This Python application serves its bundled HTML/CSS/JavaScript directly; there is no frontend build step.
The ZIP contains runtime source and static assets, plus a pinned dependency manifest. Internet access to
PyPI is required for initial dependency installation. Python 3.12+, venv and pip are required on Linux/WSL.
Direct connections additionally need the MySQL 8 client on PATH; Docker mode needs the Docker CLI and
access to the existing server containers. macOS/native Windows have not been validated.

## Connection file

Start with the [single installation guide](README.md#install). Both server types use `python3 deploy.py`; existing `--db-container` / `--world-container` commands still work.

The Hub automatically reads private `connection.json` from its own directory. Setup writes it with owner-only permissions. It is ignored by Git, excluded from public archives, and never sent to the browser. No `.env` sourcing or repeated exports are needed for file-based setup.

For unattended/direct setup, copy `examples/connection.json` to a private location, edit it with your server details, then run:

```bash
chmod 600 /path/to/my-hub-connection.json
python3 deploy.py --config /path/to/my-hub-connection.json
```

Setup saves a private copy as `connection.json`; the original file is not needed at runtime. If you place the example at `connection.json` yourself, setup also applies owner-only permissions. Use absolute paths for `dbc_path`. JSON strings containing Windows-style backslashes must escape them; WSL filesystem paths are simpler.

Direct-mode keys are `db_mode` (`direct`), `db_host`, `db_port`, `db_user`, `db_password`, `characters_schema`, `world_schema`, `auth_schema` and `dbc_path`. Standard schema names and port 3306 are defaults. `realm_id` and `host_name` are optional. The password is passed to the MySQL client through `MYSQL_PWD`, never a command-line argument. Use a dedicated SELECT-only account.

A Docker file instead uses `db_mode: "docker"`, `db_container` and `world_container`. Setup checks `/data/dbc` and then `/azerothcore/env/dist/data/dbc` inside the worldserver container automatically. Set `dbc_path` only when your DBCs are in another directory inside that container. Existing `deployment.json` files remain supported without conversion. Running `python3 deploy.py` again reuses the saved connection and reruns setup, preserving groups and local state.

The same environment variables listed below remain supported, with precedence **JOURNEY_HUB_ → legacy CHARACTER_HUB_ → legacy LEMMINGS_ → connection.json → existing deployment/default settings**. Setup rejects conflicting overrides to avoid preparing metadata against another server. Runtime environment overrides still work. The legacy `examples/connection.env` is an advanced alternative; the Hub does not automatically execute shell files.

Edit the existing `connection.json` to rotate its password or correct a path; keep it private and restart the Hub. A different realm belongs in a fresh installation directory to avoid mixing saved history. Importing a different connection over saved settings is refused.

## Server metadata

Setup generates metadata automatically from the world database and extracted server DBCs. In **direct** mode, `dbc_path` is a readable local directory on the Hub machine, normally the server's `DataDir/dbc` (or a copied directory for a remote server). No Docker CLI or running container is needed. Database reachability and SELECT grants are still required.

In **docker** mode, setup automatically checks `/data/dbc` and `/azerothcore/env/dist/data/dbc` in the selected worldserver container. If neither path matches your installation, set `dbc_path` to its DBC directory inside the container. For a mixed installation, `dbc_source` can explicitly be `local` or `docker`, independently of the database mode. The equivalent environment override is `JOURNEY_HUB_DBC_SOURCE`.

After server DBC/spell changes, rerun `python3 deploy.py` and restart the **Hub**. It never changes or restarts game containers. `--skip-assets` installs dependencies without metadata for journal-only/offline use; metadata-dependent catalogues remain unavailable until setup is rerun without it. A fresh Hub still starts with no seeded characters or journal entries.

## Settings reference

All names below have the prefix `JOURNEY_HUB_`; previous `CHARACTER_HUB_` and legacy `LEMMINGS_` names remain fallback aliases. Existing database usernames are unchanged; `journey_hub` is only the default for new direct-connection setup.
New names win when both are set. Environment overrides the saved connection file.

| Setting | Default / purpose |
| --- | --- |
| DB_MODE | `docker`; `direct` uses the local MySQL CLI over TCP |
| DB_HOST / DB_PORT | `127.0.0.1` / `3306` in direct mode |
| DB_USER / DB_PASSWORD | New setup suggests `journey_hub`; older direct setups that omit DB_USER retain `character_hub`. Password passed through MYSQL_PWD, never CLI arguments |
| DB_CONTAINER / WORLD_CONTAINER | `database` / `worldserver`; or values saved by deploy.py |
| CHARACTERS_SCHEMA / WORLD_SCHEMA / AUTH_SCHEMA | `acore_characters` / `acore_world` / `acore_auth`; SQL identifiers only |
| DBC_PATH | Local DBC directory for direct mode; optional Docker override for the directory inside the world container (auto-detected otherwise) |
| DBC_SOURCE | `local` for direct mode, `docker` for Docker mode; can override metadata location independently |
| REALM_ID | unset; choose a positive realm ID for multi-realm auth databases |
| HOST_NAME | dashboard OS hostname; optional friendly label |
| LIVE_TOKEN | optional Bearer token for a configured live quest endpoint |
| REST_MAX_BONUS | `1.5`; rested-XP cap multiplier |
| REST_OFFLINE_IN_TAVERN_OR_CITY | `1`; multiplier matching worldserver settings |
| REST_OFFLINE_IN_WILDERNESS | `1`; multiplier matching worldserver settings |
| MAX_PLAYER_LEVEL | `80`; match worldserver settings |

Use `python3 dashboard.py --help` for listen/port, watch names, MySQL/live source, live URL and check mode.
`network.json` controls the IPv4 listener and allowed hosts; `examples/network.json` is loopback-only.
Dashboard refresh controls and UI appearance/query preferences do not
change worldserver settings. Group membership, watch notes, model paths and gear roles remain local.
Client models use an optional locally supplied 3.3.5a client; no client assets ship in the package.

## Access and security

Use a SELECT-only MySQL account restricted to your dashboard machine. Required schemas are character,
world and (optionally) auth realmlist. The app reads character identities/account associations, quest
status/reward history, skills/spells/reputation, inventory/item instances, guild banks and auctions;
world tables provide quests, rewards, item templates, XP, NPC/gameobject spawns, vendors/trainers,
conditions, loot and DBC overrides. `information_schema` supplies table/column metadata. A complete
schema/table reference is in source queries; SQL explorer permits SELECTs only in character/world
schemas and disallows privileged schemas and unsafe AST nodes. Custom schema names are mapped at the
transport boundary; the explorer displays logical acore_* aliases.

Example grants for an administrator to adapt (the application never runs grants):

```sql
CREATE USER 'journey_hub'@'DASHBOARD_HOST' IDENTIFIED BY 'REPLACE_WITH_STRONG_PASSWORD';
GRANT SELECT ON acore_characters.* TO 'journey_hub'@'DASHBOARD_HOST';
GRANT SELECT ON acore_world.* TO 'journey_hub'@'DASHBOARD_HOST';
GRANT SELECT ON acore_auth.realmlist TO 'journey_hub'@'DASHBOARD_HOST';
```

Docker compatibility mode uses the existing MYSQL_ROOT_PASSWORD inside the database container and
read-only transactions; that credential has broader rights, so prefer direct SELECT-only access.
The HTTP UI has mutation tokens and Host/Origin checks, but no login/TLS or user isolation. Keep it on
loopback or a trusted private network. Game data can be sensitive. Do not expose it to the Internet.
Remote MySQL TLS settings follow the installed client's configuration; no TLS portability claim is made.

## Updates and backups

The normal update is one command, run as the same OS user who runs the Hub, from its installed folder:

```bash
python3 update.py
```

The script downloads the latest deployment ZIP and SHA-256 checksum from GitHub Releases, validates the archive and every manifest entry, stops only processes verified to belong to this Hub installation, creates a private timestamped backup, updates application files, rebuilds the Hub's Python environment and restarts a previously running Hub with its original arguments and connection environment. A health check verifies the new files are being served. A stopped Hub remains stopped. Failure automatically restores the previous files, dependencies and local databases.

For the first upgrade from an older version without this script, extract the new release and run `python3 acore-journey-hub/update.py --install /path/to/existing-hub`. It uses the verified extracted release beside that updater. The existing folder keeps its name; newly extracted packages use `acore-journey-hub/`.

### Backup and restore commands

| Command | Result |
| --- | --- |
| `python3 update.py backup` | Create and verify a backup without updating, restarting a running Hub afterwards. |
| `python3 update.py restore` | Restore the last update/manual backup, saving the current state first. |
| `python3 update.py restore --backup backups/SNAPSHOT_NAME` | Restore a specific snapshot from this installation. |
| `python3 update.py --archive /path/to/release.zip` | Update from a downloaded deployment ZIP and its adjacent `.sha256` file. |
| `python3 /path/to/new-release/update.py restore --install /path/to/existing-hub` | Recover an installation whose own updater is missing or damaged. |

Restore rolls back **both application files and saved Hub data** to that snapshot. The automatic `before-restore` backup preserves any newer notes, journal entries or screenshots before replacement. When restoring a release that predates the updater, the recovery scripts remain available so `python3 update.py` still works. Backups stay under `backups/`; they are never deleted by update or restore. Copy that directory to another disk if you also need protection from disk failure.

### What is backed up

All installed application files, `.venv`, private configuration, groups, watch lists, notes and attached images, settings, generated Hub assets, and every local SQLite database are included. This includes independent `activity.sqlite3`, `journal.sqlite3` and any other detected SQLite files, even in subdirectories. SQLite's online backup API captures committed WAL data; copied databases and file hashes are verified before a backup is marked complete.

Existing backups, generated release ZIPs under `dist/`, runtime logs/PIDs, caches, `.git` and private development-tool directories are omitted. Symlinks are preserved as links; external client or server directories are never traversed or changed. This is a Hub backup, not a backup of external linked files. The Python environment is rebuilt cleanly during update; rollback restores the previous environment.

**AzerothCore MySQL databases, game-server files and game services are always off limits for changes.** This updater neither exports nor restores game databases, runs metadata generation, edits server configuration, nor starts/stops game containers or services. The Hub's normal game access remains read-only queries.

### Access and recovery details

Public release downloads need only Python and network access. For a private GitHub repository, install/authenticate GitHub CLI once with `gh auth login`; the updater uses it when available. A downloaded ZIP with its checksum also works without GitHub access.

Automatic process control supports Linux/WSL and ordinary `bash start.sh` / `python3 dashboard.py` launches, including older Hub versions without a PID record. Only the matching installation's Python Hub server and package watcher are stopped; PID files alone are not trusted. If a service supervisor immediately restarts the Hub, stop that supervisor for maintenance and start it again afterwards. No game service is ever managed.

An interrupted update leaves a recovery record. Run `python3 update.py restore`; it selects the recorded verified backup. Corrupted or foreign-installation backups are rejected before replacing files. If the current local database is damaged, restore saves its raw bytes in the rescue backup before recovering the healthy snapshot.

The updater refuses a Git checkout or a recognizable AzerothCore game-server directory as its installation target. Keep development in the checkout and run maintenance only on your separately installed Hub copy. It does not migrate another realm's local state into your installation.

## Troubleshooting

- Missing SQLGlot: rerun `bash setup.sh --skip-assets`, then use `bash start.sh` to select `.venv`.
- Empty first page: normal; create a group. The Journal should have zero entries on first startup.
- Read-only database error: verify CLI/container access, password, SELECT grants, schema version and names.
  Root Docker mode needs MYSQL_ROOT_PASSWORD and the mysql client inside that container.
- Missing catalogue: rerun `python3 deploy.py`; check the configured local DBC directory or worldserver container.
- Missing spell/glyph tooltip details: run `.venv/bin/python prepare_tooltip_assets.py` in the deployed
  folder and restart Journey Hub. This builds local server metadata using read-only access.
- Partial/stale gameplay: MySQL shows saved server state, not unsaved world memory. Refresh cannot force a save.
- Realm unavailable: auth access is optional; check REALM_ID and SELECT on realmlist.
- Address already in use: choose `--port`; for LAN use a concrete `--allow-host` IP and trusted firewall rules.
- Direct client authentication or unsupported SQL errors: use a compatible MySQL 8 server/client; MariaDB
  is unverified and MAX_EXECUTION_TIME/session transaction variables may differ.

## Compatibility and testing boundaries

The original installation targets AzerothCore WotLK 3.3.5a with Playerbots, standard MySQL 8 JSON/window
functions, Docker and Python 3.12 on Linux/WSL. Other schema revisions/cores need validation. Playerbots
is not needed for the standalone journal or ordinary character browsing; no universal live API module
is bundled. Direct transport and custom schemas have automated command/query tests, not a second live
server compatibility certification. The supplied validation report records actual tests and limitations.

## What’s Training data

Training uses standard `trainer` and `trainer_spell` class offers, `spell_ranks`, `spell_required`,
`skilllineability_dbc` and `skillraceclassinfo_dbc`, with DBC fallbacks for spell text and eligibility.
The live request reads only `characters`, `character_spell` and `character_skills` in a bounded
read-only snapshot. Run `prepare_tooltip_assets.py` after upgrading to generate the training catalogue;
restart the app to load it. No Windows files or installed addons are required.

## Local data, network access and development

Keep `connection.json`, `deployment.json`, `groups.json`, `watchlist.json`, `watch-notes.json`, `settings.json`, `client-models.json`, `gear-planner.json`, `network.json`, `assets/` and **all** SQLite databases in your backup. In particular, independent `journal.sqlite3` stores stories and screenshot bytes; `activity.sqlite3` stores observed history. Preserve retained legacy databases too. Never overwrite these with another installation's state.

Startup is loopback-only. Optional `network.json` can set `{"listen":"0.0.0.0","allowed_hosts":["YOUR_LAN_IP"]}`. For WSL2 forwarding, the supplied `enable-lan.ps1` accepts `-LanAddress` and `-Distribution`; use the correct local addresses and host firewall. There is no HTTP login or TLS; reachable clients share local data and controls. Use only a trusted private network.

Development stays separate from deployed applications. After installing dependencies with `bash setup.sh --skip-assets`, run `.venv/bin/python -m unittest discover -s tests`, then `python3 package_release.py`. The clean ZIP is built from an explicit source allowlist. `PUBLIC_README.md` becomes the release `README.md`; maintain both source copies together. Generated metadata, private connection settings, logs and backups are never release sources.

`bash start.sh` rebuilds the clean package if source changes and starts the package watcher. Stop the app with Ctrl+C; the optional watcher PID is in `.run/package-watch.pid`. `preview.py` builds a disposable localhost:8766 installation using copies and online SQLite backups of a specified existing installation; it never deploys to that source. See `AGENTS.md` for the maintainer workflow.
