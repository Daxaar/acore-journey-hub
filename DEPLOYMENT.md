# Deployment and maintenance

This Python application serves its bundled HTML/CSS/JavaScript directly; there is no frontend build step.
The ZIP contains runtime source and static assets, plus a pinned dependency manifest. Internet access to
PyPI is required for initial dependency installation. Python 3.12+, venv and pip are required on Linux/WSL.
Direct connections additionally need the MySQL 8 client on PATH; Docker mode needs the Docker CLI and
access to the existing server containers. macOS/native Windows have not been validated.

## Install the archive

1. Verify `sha256sum -c azerothcore-character-hub-v0.1.0.zip.sha256` beside the ZIP.
2. Extract into a new directory: `unzip azerothcore-character-hub-v0.1.0.zip` then `cd character-hub`.
3. Run `bash setup.sh --skip-assets` to install SQLGlot in `.venv`.
4. For direct MySQL, copy `examples/connection.env` to `.env`, edit all connection values and run
   `chmod 600 .env; set -a; . ./.env; set +a`. The app does not automatically source `.env`.
5. For Docker mode instead, run `python3 deploy.py --db-container YOUR_DATABASE_CONTAINER --world-container YOUR_WORLDSERVER_CONTAINER`.
   This saves local `deployment.json`, installs dependencies and prepares metadata. Optional
   `--members Characterone Charactertwo --group-name 'My party' --guild-name 'My guild'`
   verifies an explicit roster; omit `--guild-name` for unguilded characters. Existing groups are retained.
6. Run `bash start.sh` and open http://localhost:8765. Create a group or open Journal immediately.
   No journal, character roster, watched bots, screenshots or history are supplied.
7. Stop with Ctrl+C. The package watcher can be stopped with `kill "$(cat .run/package-watch.pid)"`.

Docker metadata preparation reads the worldserver DBC directory and database overrides. Direct-mode
users may use Docker only for DBC access, with the direct database settings still exported. Without
metadata, the app starts and describes unavailable catalogues; profession, planner and appearance
features require their respective generated metadata. There is no published image. A Docker Compose
stack is not supplied: the current metadata workflow requires an existing world's Docker CLI access,
and host deployment avoids exposing a Docker socket to an additional application container.

## Settings reference

All names below have the prefix `CHARACTER_HUB_`; legacy `LEMMINGS_` names remain fallback aliases.
New names win when both are set. Environment overrides saved container settings.

| Setting | Default / purpose |
| --- | --- |
| DB_MODE | `docker`; `direct` uses the local MySQL CLI over TCP |
| DB_HOST / DB_PORT | `127.0.0.1` / `3306` in direct mode |
| DB_USER / DB_PASSWORD | `character_hub` / unset; password passed through MYSQL_PWD, never CLI arguments |
| DB_CONTAINER / WORLD_CONTAINER | `database` / `worldserver`; or values saved by deploy.py |
| CHARACTERS_SCHEMA / WORLD_SCHEMA / AUTH_SCHEMA | `acore_characters` / `acore_world` / `acore_auth`; SQL identifiers only |
| DBC_PATH | `/azerothcore/env/dist/data/dbc` inside the world container |
| REALM_ID | unset; choose a positive realm ID for multi-realm auth databases |
| HOST_NAME | dashboard OS hostname; optional friendly label |
| LIVE_TOKEN | optional Bearer token for a configured live quest endpoint |
| REST_MAX_BONUS | `1.5`; rested-XP cap multiplier |
| REST_OFFLINE_IN_TAVERN_OR_CITY | `1`; multiplier matching worldserver settings |
| REST_OFFLINE_IN_WILDERNESS | `1`; multiplier matching worldserver settings |
| MAX_PLAYER_LEVEL | `80`; match worldserver settings |

Use `python3 dashboard.py --help` for listen/port, watch names, MySQL/live source, live URL and check mode.
`network.json` controls the IPv4 listener and allowed hosts; `examples/network.json` is loopback-only.
UI Settings control refresh, appearance, query display policy and save-interval annotation; these do not
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
CREATE USER 'character_hub'@'DASHBOARD_HOST' IDENTIFIED BY 'REPLACE_WITH_STRONG_PASSWORD';
GRANT SELECT ON acore_characters.* TO 'character_hub'@'DASHBOARD_HOST';
GRANT SELECT ON acore_world.* TO 'character_hub'@'DASHBOARD_HOST';
GRANT SELECT ON acore_auth.realmlist TO 'character_hub'@'DASHBOARD_HOST';
```

Docker compatibility mode uses the existing MYSQL_ROOT_PASSWORD inside the database container and
read-only transactions; that credential has broader rights, so prefer direct SELECT-only access.
The HTTP UI has mutation tokens and Host/Origin checks, but no login/TLS or user isolation. Keep it on
loopback or a trusted private network. Game data can be sensitive. Do not expose it to the Internet.
Remote MySQL TLS settings follow the installed client's configuration; no TLS portability claim is made.

## Updates and backups

Stop the app before updating. Back up local JSON, assets and all SQLite files, or capture each running
SQLite database via its online backup API. The journal is independent of activity history and includes
its screenshot bytes. Install a new archive separately, verify it, then transfer only your own local
configuration/state to that installation. Never copy another realm's state. Retain the previous source
and state backup for rollback. Do not replace state with empty files from a clean installation.

## Troubleshooting

- Missing SQLGlot: rerun `bash setup.sh --skip-assets`, then use `bash start.sh` to select `.venv`.
- Empty first page: normal; create a group. The Journal should have zero entries on first startup.
- Read-only database error: verify CLI/container access, password, SELECT grants, schema version and names.
  Root Docker mode needs MYSQL_ROOT_PASSWORD and the mysql client inside that container.
- Missing catalogue: prepare armory/quest/profession/gear assets using setup against your world container.
  Crafting Rebalance additionally needs `prepare_crafting_assets.py`; see the README's feature notes.
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
