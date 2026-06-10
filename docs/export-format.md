# Export Format

The sanitized JSON export uses:

```json
{
  "format": "nte-history-export",
  "format_version": 1,
  "game": "Neverness to Everness",
  "source": "packet_capture",
  "exporter": {
    "name": "nte-history-exporter",
    "version": "0.1.0"
  },
  "banner": {
    "id": "Lottery_Permanent",
    "name": "Standard Board",
    "system": "Monopoly",
    "shared_pity": false
  },
  "scan": {
    "mode": "stable_only",
    "boundary_policy": "drop_incomplete_timestamp_groups",
    "decoded_records": 0,
    "exported_records": 0,
    "skipped_records": 0,
    "warnings": []
  },
  "records": []
}
```

Record UIDs are deterministic:

Monopoly:

```text
nte|monopoly|Lottery_Permanent|timestamp_raw|timestamp_group_ordinal|roll_result|reward_key_hex|quantity
```

Limited character records use `Lottery_LimitedCharacter` in the same UID source position.

Arc:

```text
nte|gashapon|Arc_MiracleBox|timestamp_raw|timestamp_group_ordinal|reward_key_hex
```

The final UID is `sha256(source).hexdigest()[0:32]`.

Each record includes `pool_group_id`. Arc records use the shared `reward_*` fields and include `source_type: "miracle_box"`.

Normal JSON exports do not include raw packets or capture-only metadata.
