<div align="center">

<img src="docs/images/main.png" width="200" alt="NTE History Exporter" />

# NTE History Exporter

Prototype CLI exporter for **Neverness to Everness** pull history — decodes your own game traffic into sanitized JSON ready for tracker import.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6)
![Status](https://img.shields.io/badge/status-prototype-orange)

</div>

## Supported Banners

| System   | Banner                  | Banner ID                  | Pity pool  |
| -------- | ----------------------- | -------------------------- | ---------- |
| Monopoly | Standard Board          | `Lottery_Permanent`        | Per-banner |
| Monopoly | Limited Character Board | `Lottery_LimitedCharacter` | Shared     |
| Gashapon | Arc Miracle Box         | `Arc_MiracleBox`           | Shared     |

## What It Does

The exporter decodes Permanent Board, Limited Character Board, and Arc Miracle Box history pages from captured UDP data, applies conservative timestamp-boundary handling, and writes sanitized JSON suitable for tracker import.

> [!NOTE]
> The import JSON contains decoded history rows only. It does **not** export tokens, account IDs, role IDs, device IDs, server IPs, raw packets, cookies, session data, or any other capture metadata.

## Usage

### Live capture (Windows, requires Administrator)

```powershell
.\run-exporter.ps1 --live
```

Or simply double-click **`run-exporter.cmd`** — it asks for confirmation before requesting Administrator privileges, and does nothing until you agree.

> [!IMPORTANT]
> Launch the tool **before pressing Start on the game's main menu** so the game's UDP connection can be captured. If you are already in game, log out to the main menu and enter again.

Once running, open any supported history board in game. The tool keeps listening until you press any key. Exports are written under `exports\` as:

- `Permanent_<date_time>.json`
- `Limited_<date_time>.json`
- `Arc_<date_time>.json`

If only one banner is captured, the export JSON is copied to your clipboard. If multiple banners are captured in the same run, clipboard copy is skipped so one banner does not overwrite another.

### File replay

```powershell
.\run-exporter.ps1 capture.flows
```

Decodes a `mitmproxy .flows` capture instead of listening live — used for research and testing.

### Options

| Flag      | Effect                                              |
| --------- | --------------------------------------------------- |
| `--live`  | Capture live UDP traffic instead of reading a file. |
| `--debug` | Also write the full research CSV next to each JSON. |

The `--debug` CSV holds any extra information that might be needed for fixing bugs. It contains no dangerous personal account data — only the raw bytes of the captured history page.

> [!TIP]
> For reliable deduplication, start from page 1 and scroll through the pages. If you only want pages 1–5, scroll through to page 6 as well just to be on the safe side.

## Privacy

> [!CAUTION]
> Do not commit packet captures, generated exports, research briefs, or personal account data. The repository keeps `exports/` as an empty output folder but ignores everything generated inside it.

## Boundary Policy

NTE history records do not appear to contain a unique server-side roll ID. UIDs are generated from decoded record fields and the record's order within all rows sharing the same raw timestamp.

History always loads page 1 first and is scrolled downward, so the exporter anchors to the continuous run of pages starting at page 1 and ignores anything after the first gap (with a warning). This keeps the newest pages even if a later page is lost, and guarantees the newest timestamp group's ordinal 0 is captured.

Within a timestamp group, ordinal 0 is the newest record and unseen rows can only append after the captured ones, so **every exported UID is stable** — including a partially captured oldest 10-pull. All decoded rows are therefore exported. Re-scanning later simply adds any rows that were not yet captured, with the same UIDs for the rows already seen.

For Monopoly, Points Gift and Chase Reward rows stay in the timestamp group for UID ordinal generation, but only `result_type = dice` rows count toward pull-set sizing. Arc pulls are always 10-pulls. In both systems every captured group is exported, including the oldest one even if it is a partially captured pull set, because its captured prefix is ordinal-stable.

## Adapters

**Current**

- Live Windows raw-socket capture
- `mitmproxy .flows` research decoder

**Planned**

- Live Npcap/libpcap and/or pktmon capture
- UI wrapper around the CLI

## Example Run

<div align="center">
  <img src="docs/images/cli-demo.png" width="480" alt="Live capture session: instructions, captured pages, and the results summary" />
</div>
