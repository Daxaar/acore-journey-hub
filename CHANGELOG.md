# Changelog

## 0.1.8 — 2026-11-13

Added Combat Log for original Wrath logs, with saved imports, rename and delete, time windows, group and character metrics, interactive charts and Deadmines boss filtering.

## 0.1.7 — 2026-11-12

Character roster cards show saved XP and progress toward the next level using the realm’s XP threshold. The bar appears above the quest and rested XP row and is omitted at max level or when XP data is unavailable.

## 0.1.6 — 2026-10-31

Added automated Hub-only update, full file/SQLite backups, restore and failure rollback through update.py. Updates preserve settings and local data, restart only this Hub and never modify AzerothCore databases or game servers. Deployment ZIPs now contain the acore-journey-hub folder; existing installed folders retain their names. Playerbot Watch notes support one optional image with full-size viewing.

## 0.1.5 — 2026-10-31

Renamed the product and repository to AzerothCore Journey Hub. Updated page branding, code namespaces, documentation, release names and screenshots. New environment settings use JOURNEY_HUB_; existing CHARACTER_HUB_ and LEMMINGS_ variables remain compatible. Local installation folders, saved configuration and data stay unchanged.

## 0.1.4 — 2026-10-31

Groups support ten characters across roster-backed pages, deletion asks for confirmation, and rested XP uses item-style tooltips. Setup now guides Docker and native-server users through a saved private connection file; direct MySQL metadata reads local server DBCs without Docker. Installation has one canonical release-first guide, with current feature usage in separate FEATURES.md. Existing container configuration and environment overrides remain supported.

## 0.1.3 — 2026-10-31

Added an optional Wrath of the Lich King theme with original frozen-citadel artwork, icy blue accents, steel panels and matching navigation states. Quest objective, quest-starting and provided-item links now use shared item tooltips while preserving Wowhead navigation. Existing themes and preferences are preserved. The clean deployment archive includes deploy.py, setup.sh, start.sh and the isolated preview.py script.

## 0.1.2 — 2026-10-30

Added orange profession-rank training indicators and character badges, using server skill and character-level requirements through Grand Master. Character training tooltips now match item tooltip styling and support keyboard focus. Added an isolated preview script with port-conflict detection and source verification, plus agent instructions requiring a preview link and treating the live installation as read-only.

## 0.1.1 — 2026-10-30

Decorative navigation tabs with consistent positions across pages; dedicated Inventory for carried bags, personal bank and guild bank; Auction House naming and shared content width. Includes What’s Training and shared server-backed item tooltips. Removed the retired Crafting Rebalance feature.

- Added decorative page tabs and a separate Inventory page for bags and banks. Removed the retired Crafting Rebalance catalogue and review feature; normal profession recipes remain available.

## 0.1.0 — 2026-10-29

First generic Journey Hub preview release. Retains existing dashboard features, removes guild-specific startup branding and roster discovery, adds portable configuration and versioned release archives. Existing installations remain separate and unchanged.

Shared server-backed item tooltips now cover equipment, bags/banks, quests, professions, auctions, crafting and gear planning. Recipe cast/tool/reagent context, spell and glyph effects, requirements, gems/sockets, set descriptions and saved-instance details are displayed where resolvable. Added conservative spell-text parsing, bounded cached lookups and browser/API regressions.

Added What’s Training: class-trainer progression, rank/known-state handling, exact-level/range and name filters, ability tooltips and shared group navigation. Class/race, skill and prerequisite checks use saved server data; client-dependent values are labelled. Includes synthetic browser and read-only API regressions.
