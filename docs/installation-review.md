# Installation and feature-documentation review — 2026-10-31

Tracked in #6. Dashboard group/tooltip changes were delivered separately through #5 / PR #7.

## Findings and changes

| Finding | Resolution |
| --- | --- |
| README linked to a Docker-only QUICKSTART, while both contained different installation/deployment steps. | README is the canonical three-step release-install guide for Docker and direct MySQL. QUICKSTART only points to it. |
| End users were asked to clone/build the repository before installing an existing release. | GitHub Release ZIP/checksum is the primary distribution. Developer builds stay in DEPLOYMENT.md. |
| Direct MySQL existed, but only through manually exported shell variables. | Setup prompts for a native connection or imports a Hub JSON file; runtime and asset generators automatically load the private saved file. |
| Metadata readers always invoked Docker. | A shared reader accepts local extracted DBCs in direct mode, and retains container reads for Docker. An explicit DBC-source override supports mixed configurations. |
| Setup had mandatory container arguments. | No-argument deploy.py guides either server type, reuses saved configuration on rerun, and preserves legacy container arguments/files. |
| Feature sections were interleaved with installation, configuration and development material. | FEATURES.md is a separate catalogue and usage guide; advanced operations live in DEPLOYMENT.md. |
| The core feature matrix was mostly accurate, but Auction Exchange naming and Docker-only descriptions were stale. | Use current Auction House navigation names and connection-independent descriptions. |
| Recent Wrath appearance/navigation, ten-member groups, delete confirmation, rested tooltips, broader quest-item hovers and profession-rank indicators were missing or buried. | Explicitly document those capabilities alongside the current pages. |
| Older screenshots do not show every new control/theme; some future-work prose sounded like released functionality. | Label screenshots illustrative and separate present limitations from implemented capabilities. |

## Native-server configuration decision

Use a private Hub connection.json, not an automatic worldserver.conf credential importer. The install guide explains CharacterDatabaseInfo, WorldDatabaseInfo, LoginDatabaseInfo and DataDir using the [AzerothCore setup reference](https://www.azerothcore.org/wiki/linux-server-setup). Users enter the host/schema information and a dedicated SELECT-only account; the Hub does not alter the server file or silently reuse server credentials. Remote native servers need readable matching DBCs copied to the Hub machine.

## Validation scope

Synthetic tests cover connection-file validation, environment precedence, passwords outside command arguments, owner-only persistence, local DBC parsing, preserved container reads, legacy setup, config import/rerun behavior, preview configuration isolation and release exclusion of secrets. All 253 regression tests passed. A clean extracted archive installed dependencies, saved direct settings, loaded them in a fresh process and started with empty groups/journal through bash start.sh, using a synthetic MySQL client and no game connection. Clean packaging and the isolated preview were verified. A second live native realm and native Windows/macOS are not certified by this work.
