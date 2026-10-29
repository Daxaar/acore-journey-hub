# Quickstart: existing AzerothCore Docker containers

For **Ubuntu 24.04+ or Ubuntu 24.04+ in WSL2**, with an existing AzerothCore WotLK
3.3.5a/MySQL 8 installation and working Docker access. Docker setup is assumed.
Run these commands in your Linux/WSL terminal. You need internet access, `sudo`,
and GitHub access to the private `Daxaar/acore` repository.

## 1. Install Character Hub prerequisites

```bash
sudo apt update
sudo apt install -y git gh python3 python3-venv python3-pip
python3 --version
```

Python must be **3.12 or newer**.

## 2. Sign in and download the source

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
cd ~
git clone --branch character-hub/generalise-v0.1.0 --single-branch https://github.com/Daxaar/acore.git acore-character-hub
cd ~/acore-character-hub/character-hub
```

Follow the browser sign-in prompts using an account with repository access. The
branch above contains Character Hub while its draft PR awaits merge. Use a new
folder; do not copy another installation's configuration or databases into it.

## 3. Select your existing containers

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}'
```

Set these to the exact database and worldserver container names from that list:

```bash
DB_CONTAINER='YOUR_DATABASE_CONTAINER'
WORLD_CONTAINER='YOUR_WORLDSERVER_CONTAINER'
```

For nonstandard database schemas or DBC paths, see [configuration](DEPLOYMENT.md#settings-reference).

## 4. Configure and install

```bash
python3 deploy.py --db-container "$DB_CONTAINER" --world-container "$WORLD_CONTAINER"
```

Wait for **Deployment ready**. This saves your container names, creates `.venv`,
installs the pinned dependency and builds metadata from your server. It reads game
data without changing your game containers.
If it fails, correct the reported problem and rerun the same command.

## 5. Start and use Character Hub

```bash
bash start.sh
```

Leave that terminal open. On the same machine, open **http://localhost:8765** in
your browser (the Windows browser works for WSL2 too).

On **Dashboard → Manage groups**, create a group with 1–6 existing character names.
Click **Refresh Now** to load their saved data. New installations have no groups,
watched bots or journal entries; add your own as needed.

Press **Ctrl+C** to stop the app. To start it again:

```bash
cd ~/acore-character-hub/character-hub
bash start.sh
```

**Optional:** Crafting Rebalance needs an additional catalogue. With the app stopped,
run `.venv/bin/python prepare_crafting_assets.py`, then start it again. This downloads
a pinned reference dataset. 3D previews require your own compatible game client;
see the [full README](README.md). These are not required for basic character browsing.
