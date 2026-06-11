# NTE History Exporter

Prototype CLI exporter for Neverness to Everness pull history.

This version supports:

- Game: Neverness to Everness
- System: Monopoly
- Banner ID: `Lottery_Permanent`
- Banner name: Standard Board / Permanent Board
- Banner ID: `Lottery_LimitedCharacter`
- Banner name: Limited Character Board
- System: Gashapon
- Banner ID: `Arc_MiracleBox`
- Banner name: Arc Miracle Box

## What It Does

The exporter decodes Permanent Board, Limited Character Board, and Arc Miracle Box history pages from captured UDP data, applies conservative timestamp-boundary handling, and writes sanitized JSON suitable for tracker import.

It does not export tokens, account IDs, role IDs, device IDs, server IPs, raw packets, cookies, session data, or other capture metadata. The import JSON contains decoded history rows only.

## Privacy

Do not commit packet captures, generated exports, research briefs, or personal account data. The repository keeps `exports/` as an empty output folder, but ignores everything generated inside it.

## Usage

Live capture, Windows:

```powershell
.\run-exporter.ps1 --live
```

Launch it before pressing Start on the game's main menu so the game's UDP connection can be captured, then open any supported history board in game. If you are already in game, log out to the main menu and enter again. The tool keeps listening until you press any key. Exports are written under `exports\` as `Permanent_<date_time>.json`, `Limited_<date_time>.json`, or `Arc_<date_time>.json`.

Pass `--debug` to also write the full research CSV next to each JSON export.

If only one banner is captured, the export JSON is copied to the clipboard. If multiple banners are captured in the same run, clipboard copy is skipped so one banner does not overwrite another.

File replay:

```powershell
.\run-exporter.ps1 capture.flows
```

For reliable deduplication, start from page 1 and scroll downward. If you only want pages 1-5, scroll through page 6 as well so the exporter can confirm the final timestamp group boundary.

Limited character history is exported as one shared pity pool: `Lottery_LimitedCharacter`.
Arc Miracle Box history is exported as one shared pity pool: `Arc_MiracleBox`.

Live capture needs a local admin-capable packet socket on Windows. The prototype uses the built-in raw socket path first, without requiring mitmproxy capture files.

## Boundary Policy

NTE history records do not appear to contain a unique server-side roll ID. UIDs are generated from decoded record fields and the record's order within all rows sharing the same raw timestamp.

History always loads page 1 first and is scrolled downward, so the exporter anchors to the continuous run of pages starting at page 1 and ignores anything after the first gap (with a warning). This keeps the newest pages even if a later page is lost, and guarantees the newest timestamp group's ordinal 0 is captured.

Within a timestamp group, ordinal 0 is the newest record and unseen rows can only append after the captured ones, so every exported UID is stable. The one nuance is the oldest captured group: if the capture did not reach the true end of history and its dice-roll count is not a complete multiple of 10, it may be an unfinished 10-pull continuing onto an uncaptured page. Its captured prefix is still ordinal-stable, so it is exported with an informational warning telling you to scroll further to capture the rest.

For Monopoly, Points Gift and Chase Reward rows stay in the timestamp group for UID ordinal generation, but only `result_type = dice` rows count toward pull-set sizing. Arc pulls are always 10-pulls, so the same rule applies with a fixed group size of 10. In both systems the oldest captured group is exported even if it is an unfinished pull set (its captured prefix is ordinal-stable), and flagged with a warning so you know to scroll further on a later scan.

## Current Adapters

- live Windows raw-socket capture
- `mitmproxy .flows` research decoder

Planned later:

- live Npcap/libpcap capture
- UI wrapper around the CLI
