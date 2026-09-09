# Export Format

The JSON export is the format to use when building tools around captured NTE
history. It is cleaned for import/use and does not include raw packet bytes or
decoder-only offsets.

## JSON shape

```json
{
  "format": "nte-history-export",
  "format_version": 1,
  "game": "Neverness to Everness",
  "source": "packet_capture",
  "capture_source": "npcap",
  "exporter": {
    "name": "nte-history-exporter",
    "version": "0.3.2"
  },
  "banner": {
    "id": "Lottery_Permanent",
    "name": "Standard Board",
    "system": "Monopoly",
    "shared_pity": false
  },
  "scan": {
    "mode": "stable_only",
    "boundary_policy": "export_ordinal_stable_groups",
    "decoded_records": 0,
    "exported_records": 0,
    "skipped_records": 0,
    "warnings": []
  },
  "user_uid": "optional-user-uid",
  "server_id": "23003",
  "account_region": "EU",
  "records": []
}
```

Top-level fields:

- `format` / `format_version`: Identify this export format.
- `game`: Game name.
- `source` / `capture_source`: Where the export came from.
- `exporter`: Exporter name and version.
- `banner`: The history pool this file belongs to.
- `scan`: Export counts and capture warnings.
- `user_uid`: Optional game account UID, if known.
- `server_id`: Optional numeric account-server ID, detected from the initial TCP
  connection or selected by the user.
- `account_region`: Region code mapped from a known production `server_id`.
  Current values are `AS`, `NA_SA`, `EU`, and `SE`. It is omitted for an
  unrecognized server ID rather than guessed.
- `records`: Pull/reward records.

## Fields to identify pulls

For most tools, prefer these fields:

- `uid`: Stable unique ID for this exported pull/reward row.
- `user_uid`: Account UID, when present. Use this with `uid` if storing data for
  multiple accounts.
- `pool_group_id`: Stable pool ID for the record.
- `banner.id`: Stable pool ID for the whole file. This should match
  `pool_group_id` on records.
- `timestamp`: Display timestamp from the game history.
- `timestamp_group_ordinal`: Stable ordering inside records that share the same
  timestamp.
- `reward_id`: Stable decoded reward ID.
- `reward_type`: Reward category, such as `character`, `item`, or `arc`.
- `quantity`: Reward quantity, for Monopoly records.
- `roll_result` / `result_type`: Monopoly result details.

Current stable pool IDs:

- `Lottery_Permanent`: Standard Board.
- `Lottery_LimitedCharacter`: Limited Character Board. New limited character
  banners should still use this ID while they share the same history/pity pool.
- `Arc_MiracleBox`: Arc Miracle Box.
- `Gashapon_MysteryBox`: Mystery Box. Records are single pulls and history is
  not split into event rotations by the exporter.

Avoid using `banner.name`, `reward_name`, `reward_type` or `reward_rank` as primary IDs. They
are useful display fields, but may change when mapping files are updated.

Known `reward_id` values are matched case-insensitively and emitted using the
canonical casing from the bundled mapping. This prevents packet/asset casing
differences from dropping display metadata or producing different downstream
IDs. An unknown reward keeps the casing decoded from the packet. Reward IDs are
not UID inputs, so canonicalizing their casing does not change pull UIDs.

## Stability notes

Every JSON record is exported with a stable `uid`. Re-scanning deeper history can
add older rows, but already exported rows keep the same `uid`.

Limited character banners are grouped by their shared history pool, not by the
currently featured character. If the game adds a new visible limited character
banner that uses the same pool, tools should continue treating it as
`Lottery_LimitedCharacter`.

If the game adds a genuinely new history pool, the exporter mappings need to be
updated before tools can identify it cleanly. Reward display data also comes from
the mapping files, so new rewards may export with stable IDs before they have
nice names or ranks.

## UID generation

The `uid` is the first 32 hex characters of `sha256(source)`. The game does not
appear to send a stable pull/reward row ID, so the exporter builds one from the
history pool, raw packet timestamp, and ordinal inside that timestamp group.
Decoded content such as dice result, reward ID, and quantity is intentionally
excluded so decoder fixes do not change the identity of an already-captured row.

Monopoly source:

```text
nte|monopoly|pool_group_id|timestamp_raw|timestamp_group_ordinal
```

Arc source:

```text
nte|gashapon|pool_group_id|timestamp_raw|timestamp_group_ordinal
```

Mystery Box uses the same Gashapon UID source. Reward quantity is preserved,
but each record represents exactly one pull and has `result_type = single_pull`.

## Example records

Monopoly:

```json
{
  "uid": "7aae34232160e950ecc7b5da38812caa",
  "pool_group_id": "Lottery_LimitedCharacter",
  "timestamp": "2026-06-10 13:32:17",
  "timestamp_group_ordinal": 0,
  "roll_result": 5,
  "result_type": "dice",
  "reward_type": "character",
  "reward_id": "1033",
  "reward_name": "Adler",
  "reward_rank": "A",
  "quantity": 1
}
```

Arc:

```json
{
  "uid": "75c42ad1171d1d0f72b2c8d8307f7230",
  "pool_group_id": "Arc_MiracleBox",
  "timestamp": "2026-06-10 23:46:29",
  "timestamp_group_ordinal": 0,
  "reward_type": "arc",
  "reward_id": "fork_nonos",
  "reward_name": "First Step to Success",
  "reward_rank": "B",
  "source_type": "miracle_box"
}
```

Mystery Box:

```json
{
  "uid": "2610c6e96afd64aa4a53fb9e8cebe031",
  "pool_group_id": "Gashapon_MysteryBox",
  "timestamp": "2026-07-08 19:09:33",
  "timestamp_group_ordinal": 0,
  "result_type": "single_pull",
  "reward_type": "item",
  "reward_id": "vehicle039",
  "reward_name": "Draco",
  "reward_rank": "S",
  "quantity": 1,
  "source_type": "mystery_box"
}
```

## Achievement export

Achievements are written separately as
`<user_uid>_Achievements_<date_time>.json`. The document contains only records
observed in the account's login response; definitions found only in the asset
mapping are not synthesized into the export.

```json
{
  "format": "nte-achievement-export",
  "format_version": 1,
  "game": "Neverness to Everness",
  "source": "live_capture",
  "capture_source": "npcap",
  "exporter": {
    "name": "nte-history-exporter",
    "version": "0.3.2"
  },
  "scan": {
    "in_game": {
      "total_achievements": 367,
      "completed_achievements": 310,
      "in_progress_achievements": 57
    },
    "playstation": {
      "total_achievements": 35,
      "completed_achievements": 31,
      "in_progress_achievements": 4
    }
  },
  "user_uid": "218216016349",
  "server_id": "23003",
  "account_region": "EU",
  "categories": {
    "battle": [
      {
        "id": "Battle_25",
        "platform": "in_game",
        "status": "in_progress",
        "progress": 20,
        "completed": false,
        "completed_at": null,
        "name": "Devil Within II",
        "description": "Trigger Hexed ×50.",
        "quality": "high",
        "target": 50,
        "rewards": [
          {"item_id": "Annulith", "amount": 10}
        ]
      }
    ]
  }
}
```

Achievement fields:

- `scan.in_game` and `scan.playstation` separate records visible in game from
  PlayStation trophy records and report completed/in-progress totals.
- `categories` groups records by the prefix of their captured ID. The category
  is therefore not repeated on every record.
- `status` is `completed` when completion ticks are present and `in_progress`
  otherwise. An observed compound achievement can be in progress while its
  numeric `progress` is zero because individual checklist state is server-side.
- `completed_at` is a decoded UTC time for completed records and `null` for
  in-progress records.
- `name`, `description`, `quality`, `target`, and `rewards` are optional display
  metadata from `mappings/achievements.json`.
- A newly captured ID missing from the bundled mapping still exports its core
  captured fields; only optional display metadata is omitted.
- Asset definitions absent from the network response are not exported because
  absence cannot distinguish unstarted, locked, or unavailable content.

## CSV diagnostics

CSV exports are mainly for debugging the decoder. Tools should prefer JSON
unless they specifically need raw packet details.
