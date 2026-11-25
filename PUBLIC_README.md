# AzerothCore Journey Hub

A private dashboard for your existing **AzerothCore WotLK 3.3.5a** server.
Game data is read only. The Hub keeps its own groups, notes and journal locally.

**[Features and screenshots](FEATURES.md)** · **[Releases](https://github.com/Daxaar/acore-journey-hub/releases)** · **[Advanced configuration and updates](DEPLOYMENT.md)**

## Before you start

Run the Hub on **Linux or WSL with Python 3.12+, venv and pip**. Initial setup needs an internet connection to install its Python dependency.
The game server can run in containers or as a normal installation; it can be on another machine.
Native Windows/macOS Hub installations have not been validated.

Have the details for **one** connection method ready:

| Your server | What the Hub needs |
| --- | --- |
| Docker | Docker CLI access to the server, and the database and worldserver container names. Use `docker ps` to find them. |
| No containers | MySQL 8 command-line client on the Hub machine; database host, port, username/password and database names; a readable copy of the server's extracted `data/dbc` directory on the Hub machine. |

For a non-container server, use a **SELECT-only MySQL account** with access to the character and world databases; access to `auth.realmlist` adds the realm label.
An administrator can use the [example grants](DEPLOYMENT.md#access-and-security).
The game server's `worldserver.conf` identifies the database names and `DataDir`; details are [below](#finding-your-native-server-settings).

## Install

### 1. Download and extract

From the [latest GitHub Release](https://github.com/Daxaar/acore-journey-hub/releases/latest), download the **deployment ZIP** and matching **`.sha256` file** under Assets. GitHub's automatic “Source code” downloads are for development.
Put both files in the same directory. For v0.1.6:

```bash
sha256sum -c azerothcore-journey-hub-v0.1.6.zip.sha256
python3 -m zipfile -e azerothcore-journey-hub-v0.1.6.zip .
cd acore-journey-hub
```

The ZIP extracts into `acore-journey-hub/`. Existing installations can stay in their current folder; the updater does not rename them.

Extract into a new directory. To replace an existing installation, follow [Updates and backups](DEPLOYMENT.md#updates-and-backups) instead.

### 2. Run setup

```bash
python3 deploy.py
```

Choose **docker** or **direct** (no containers), then answer the prompts.
Setup saves your choices in a private `connection.json`, installs dependencies and builds the server metadata. Password entry is hidden. It does not alter or restart AzerothCore.
In Docker mode, setup automatically checks `/data/dbc` and `/azerothcore/env/dist/data/dbc` in the selected worldserver container. If your DBCs are elsewhere in that container, set `dbc_path` in `connection.json` to their directory.

When setup says **Setup ready**, continue. If it reports a missing prerequisite or connection problem, correct it and rerun the same command; saved settings are reused.

Prefer editing a file? Copy `examples/connection.json` to a private file outside the Hub directory, fill in your own values, then run `python3 deploy.py --config /path/to/your-connection.json`. Setup saves an owner-only copy inside the Hub. See the [configuration reference](DEPLOYMENT.md#connection-file).

### 3. Start

```bash
bash start.sh
```

Open **[http://localhost:8765](http://localhost:8765)**. Create your first group on the Dashboard, or start writing in the Journal.
New installations have no characters, groups, watched bots, notes, history or journal entries.

Leave the terminal open. Stop the Hub with **Ctrl+C**. Next time, run `bash start.sh` from the same directory; you do not need to enter connection settings again.

## Update, back up or restore

From your installed Hub folder:

```bash
python3 update.py
```

This downloads and verifies the latest release, stops only the Hub, backs up all its files and local SQLite databases, installs the update and checks the restarted Hub. Existing settings and data are kept. If the update fails, the previous installation is restored automatically. A stopped Hub stays stopped.

To roll back later, including the saved data from before the update:

```bash
python3 update.py restore
```

For a backup without updating, use `python3 update.py backup`. Backups are kept privately under `backups/`; restore also saves the current state before replacing it. **These commands never back up or change AzerothCore databases, game-server files or game services.**

Upgrading from a version without `update.py`? Extract the new release, then run its updater once, pointing to your existing installation:

```bash
python3 acore-journey-hub/update.py --install /path/to/your/existing-hub
```

After that, use `python3 update.py` inside the existing folder. See [maintenance options](DEPLOYMENT.md#updates-and-backups) for a downloaded ZIP, a specific backup or private-repository access.

## Finding your native-server settings

In the server's `worldserver.conf`, look for:

- `CharacterDatabaseInfo`, `WorldDatabaseInfo` and `LoginDatabaseInfo`: database connection entries formatted as `host;port;user;password;database` for a normal TCP configuration.
- `DataDir`: the server data directory. The Hub needs its **`dbc` subdirectory**, containing files such as `Spell.dbc` and `ItemDisplayInfo.dbc`.

Use the database host/port and names to fill in setup, but use your dedicated Hub database username/password. The Hub does not import or edit `worldserver.conf` or copy its server credentials.
For a remote server, allow the Hub's database account to connect from the Hub machine and copy the matching extracted `dbc` directory to that machine. The Hub needs neither maps nor vmaps/mmaps.
Relative `DataDir` paths are relative to the server's working directory, not the Hub directory. See [AzerothCore's server setup reference](https://www.azerothcore.org/wiki/linux-server-setup).

## Help and maintenance

- **Setup fails:** check the reported prerequisite, database credentials, read permissions and DBC directory. Rerun `python3 deploy.py` after fixing them.
- **No game data yet:** create a group with real character names; a new Hub deliberately starts empty. Game progress reflects database saves.
- **Custom settings, network access or upgrades:** use [DEPLOYMENT.md](DEPLOYMENT.md).
- **Using the dashboard:** see [FEATURES.md](FEATURES.md). Installation steps are kept here.
- **Problems or requests:** open a [GitHub issue](https://github.com/Daxaar/acore-journey-hub/issues) without passwords or private configuration.

The source is [MIT licensed](LICENSE). Third-party licences are included under `third_party/`. No game client files or generated game assets are distributed.

## Transaction history

The Transactions page works with [mod-transaction-journal](https://github.com/Daxaar/mod-transaction-journal).
Install the module and apply its journal SQL migrations on your server first. Select monitored characters in the Hub; new characters default to off.
The module records loot, per-character money shares, vendor trades and Auction House observations. Historical records can be filtered, exported as JSON, or removed for one character after confirmation.

Point the Hub at the shared monitoring file using the JOURNEY_HUB_TRANSACTION_MONITORING environment variable or a local transaction-journal.json file:

```json
{"monitoring_file": "/path/shared-with-worldserver/transaction-monitoring.txt"}
```

Configure TransactionJournal.MonitoringFile with the corresponding path visible to worldserver. Both processes need appropriate access to that directory and its transaction-journal-requests subdirectory. The Hub queries game data read-only. Explicit history removal is performed by the module against its own journal table.

Auction records are observations before commit. Vendor refunds, token costs and buyback purchases are outside the current capture coverage. Older records can have unknown loot sources. Loot vendor totals use current base vendor prices and include all matching pages.

## Mailbox and postage

Mailbox provides a read-only inbox and letter view for online and offline characters, including attachments, money, COD and delivery/expiry times. Viewing messages leaves their recorded read state and contents intact.

Update mod-transaction-journal and apply its 003_mail_sends.sql migration before upgrading to Hub 0.1.13. New paid sends by or involving monitored characters are recorded as mail_sent_observed. Transactions separates postage paid, attached gold and requested COD. Postage summaries are sender-scoped. These pre-commit observations do not prove delivery or collection, and old postage is not reconstructed from existing inboxes.

Transactions supports editable Dungeon/Zone suggestions and clickable column sorting across the whole filtered result and exported JSON. Location filters require recorded location fields.

### Live World

The optional separate [mod-bot-monitor](https://github.com/Daxaar/mod-bot-monitor) exporter supplies current online population, zone counts, character positions, XP and active quest logs without game-database writes. Open **Live World**, click a zone and then a character. Filters apply to the counts and zone lists. Positions normally refresh every five seconds; quest logs refresh every thirty seconds. Coordinates are raw world coordinates; session age is account-session age, not precise character login duration.

Configure a private `bot-monitor.json` beside the Hub with a `directory` pointing to the exporter's shared directory, or set `JOURNEY_HUB_BOT_MONITOR_DIRECTORY`. The Hub needs read access to `snapshot.json` and write access to the directory for atomic `control.txt` updates. Keep this directory private. No TCP listener is added to the worldserver. Control uses the Hub's existing same-origin/session-token protection; restrict Hub access to trusted users because they can enable or disable monitoring.

The module's startup gate defaults off. Once permitted, the Hub capture checkbox controls sampling; Off stops character scans and recurring snapshot writes, leaving one small control-file check per second. Stale snapshots show a warning instead of live counts or positions. No history is stored in this first version.

Live World faction emblems use the original client `Interface/TargetingFrame/UI-PVP-Alliance.blp` and `UI-PVP-Horde.blp` artwork. Prepare these local-only assets with `python3 prepare_faction_assets.py /path/to/WoW` (use `--output /path/to/hub/static` for another installation). Client artwork is excluded from public source packages. Missing artwork hides the image; the faction remains available in the name tooltip and character details.

For the optional Live World coordinate maps, run `python3 prepare_live_world_maps.py /path/to/WoW` in the Hub installation. This reads only coordinate bounds from the local Wrath client into `assets/live-world-maps.json`. The schematic continent and zone views use the existing snapshot, group nearby dots into clickable clusters, and open Armory from a character dot. Instance floors are outside this version.

### Optional Live World background images

Place your own WebP images (up to 8 MiB each) in `assets/map-backgrounds/`. Name them `continent-0.webp`, `continent-1.webp`, `continent-530.webp`, `continent-571.webp`, or `zone-<map-id>-<zone-id>.webp` (for example, `zone-0-40.webp` for Westfall). Each image must cover the entire corresponding map bounds without margins. Enable **Use map backgrounds from my WoW client** in Settings and reload Live World. The schematic remains visible where a background is missing. The Hub serves enabled images to its users. Supply artwork you have permission to display. Local images are excluded from Git and releases.

The **Use map backgrounds from my WoW client** setting uses the configured WoW 3.3.5a client folder, independently of whether 3D character models are enabled. The Hub reads existing outdoor map tiles as needed and displays them with the Live World overlay. The WebP folder above remains an optional fallback. No client images are included in the package.

Outdoor backgrounds include the client’s exploration overlays where available, so landmarks appear without requiring character exploration. The overlay is visual only.

Live World warms the four continents and up to eight busy zones once per 20-minute window. The low-priority Hub worker decodes one map at a time. The in-memory cache retains up to 64 MiB of compressed tiles for 20 minutes after use, with older entries evicted when full. It is rebuilt after a Hub restart.

Live World shows XP gained since the Hub first observed each online session. The calculation uses the existing snapshots, including XP carried over a single level-up. A skipped level or XP reset marks the result as partial. Tracking resets when the Hub restarts and samples only while Live World is being read.

## Optional auction market integration

The Forever Auction House tab browses archived WoW Forever EU PvE Alliance listings. Market Preview shows feed freshness, coverage, import history and estimated sales activity. Exact listing-price matches cannot identify which feed originally priced an auction.

The optional hourly market worker archives Forever and Anniversary snapshots outside the installation. It can publish an item ID and copper-per-unit CSV for an AHBot Plus build with market-file support. Eligible Forever prices take precedence, and Anniversary fallback requires regional sales activity. The publisher can use history when Forever is stale. Items without an override retain formula pricing.

For an existing collector, set JOURNEY_HUB_MARKET_DATA to its archive directory if it differs from the default, JOURNEY_HUB_MARKET_PRICE_DIR to its published-price directory and JOURNEY_HUB_MARKET_BOT_IDS to the comma-separated seller GUIDs for coverage reporting. Start the worker with its own installation-specific policy using market_worker.py --policy PATH. The policy defines mode, output, freshness_hours, optional pilot and bot_ids. The worker and Hub require their usual read-only game database access for local metrics. Keep policy, archives and credentials local.
