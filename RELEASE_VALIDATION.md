# Character Hub v0.1.0 validation — 2026-10-29

## Completed

- 226 Python unit/integration tests passed on Python 3.12, including HTTP endpoints, group/watch limits,
  source outages, SQL restrictions, history, quest eligibility, armory, professions, gear planning,
  auction browsing, journal conflicts/screenshots/tags, settings, crafting reviews and release hygiene.
- Release ZIP extracted into a fresh disposable official Python 3.12 slim container, with no mounted
  game data, private configuration or credentials. Ran the documented `bash setup.sh --skip-assets`
  followed by `bash start.sh --port 18766`. SQLGlot 30.24.0 installed from the pinned manifest.
- Clean HTTP journal API returned zero entries, and its new SQLite tables contained zero records.
  No journal database or screenshot bytes were included in the release archive. No seeded groups,
  characters, watched bots, notes, history or review decisions are included.
- All 226 tests passed again from the extracted archive using its newly installed virtual environment.
- Playwright Chromium checked clean Overview, Journal, Armory and Gear Planner pages with no browser
  errors. Screenshots show only empty/setup states and an example host label.
- Read-only live comparisons between original and generic adapters returned matching character
  snapshots, equipment/inventories and completed quest records for all nine characters in saved groups.
- Original source/configuration compared to the private pre-change backup: 1,005 files unchanged.
  Original activity and independent journal databases matched their online backups by logical dump
  hash and table counts. No game-server writes, migrations, restarts or configuration changes ran.
- ZIP allowlist, per-file manifest hashes, reproducibility, exclusion of private state and SHA-256
  checksum checks passed. New source and clean documentation screenshots are explicitly allowlisted.
- Repository metadata confirmed Daxaar/acore is private. The owner explicitly approved a private
  development branch, source/ZIP upload and draft pull request in chat. No merge, public release,
  image publication or visibility change is included in this delivery.

## Scope and limits

The local sandbox lacked pip/ensurepip, so installation was validated in the disposable official runtime
with the documented prerequisites rather than changing the host's Python packages. Original deployment
remains intact. The disposable container was removed after testing.

No second independent game server was available. Direct TCP credentials, custom schema remapping,
optional guild/group discovery and new/legacy environment precedence have automated tests; direct
MySQL transport is not certified against another live installation. Metadata generation still requires
world-container DBC access. Linux/WSL Python 3.12 and existing AzerothCore WotLK/MySQL assumptions are
supported; native Windows/macOS, MariaDB and divergent schemas need manual validation.

A full populated browser walkthrough of every live feature was not repeated; original source is
unchanged, existing feature tests passed and selected live database outputs were compared. No claim
is made that all external clients/server variants or unsaved in-world data were tested.

## Before public publication

Owner review of the proposed MIT licence, third-party notices and complete source/privacy review;
independent realm compatibility testing; decisions on authentication/TLS and hosting; and explicit
approval for any public repository, public release or container-registry publication remain necessary.
The included monorepo workflow template needs owner installation at the repository root to enable CI.
