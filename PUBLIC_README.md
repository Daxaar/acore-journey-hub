# AzerothCore Character Hub

A private dashboard for your existing **AzerothCore WotLK 3.3.5a** server.
Game data is read only. The Hub keeps its own groups, notes and journal locally.

**[Features and screenshots](FEATURES.md)** · **[Releases](https://github.com/Daxaar/acore-character-hub/releases)** · **[Advanced configuration and updates](DEPLOYMENT.md)**

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

From the [latest GitHub Release](https://github.com/Daxaar/acore-character-hub/releases/latest), download the **deployment ZIP** and matching **`.sha256` file** under Assets. GitHub's automatic “Source code” downloads are for development.
Put both files in the same directory. For v0.1.4:

```bash
sha256sum -c azerothcore-character-hub-v0.1.4.zip.sha256
python3 -m zipfile -e azerothcore-character-hub-v0.1.4.zip .
cd character-hub
```

Extract into a new directory. To replace an existing installation, follow [Updates and backups](DEPLOYMENT.md#updates-and-backups) instead.

### 2. Run setup

```bash
python3 deploy.py
```

Choose **docker** or **direct** (no containers), then answer the prompts.
Setup saves your choices in a private `connection.json`, installs dependencies and builds the server metadata. Password entry is hidden. It does not alter or restart AzerothCore.

When setup says **Setup ready**, continue. If it reports a missing prerequisite or connection problem, correct it and rerun the same command; saved settings are reused.

Prefer editing a file? Copy `examples/connection.json` to a private file outside the Hub directory, fill in your own values, then run `python3 deploy.py --config /path/to/your-connection.json`. Setup saves an owner-only copy inside the Hub. See the [configuration reference](DEPLOYMENT.md#connection-file).

### 3. Start

```bash
bash start.sh
```

Open **[http://localhost:8765](http://localhost:8765)**. Create your first group on the Dashboard, or start writing in the Journal.
New installations have no characters, groups, watched bots, notes, history or journal entries.

Leave the terminal open. Stop the Hub with **Ctrl+C**. Next time, run `bash start.sh` from the same directory; you do not need to enter connection settings again.

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
- **Problems or requests:** open a [GitHub issue](https://github.com/Daxaar/acore-character-hub/issues) without passwords or private configuration.

The source is [MIT licensed](LICENSE). Third-party licences are included under `third_party/`. No game client files or generated game assets are distributed.
