# Export Format

The sanitized JSON export uses:

```json
{
  "format": "nte-history-export",
  "format_version": 1,
  "game": "Neverness to Everness",
  "source": "packet_capture",
  "capture_source": "npcap",
  "exporter": {
    "name": "nte-history-exporter",
    "version": "0.1.3"
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

Example Monopoly pull record:

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

Example Arc record:

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

Normal JSON exports do not include raw packets or capture-only metadata.
`user_uid` is included when detected automatically or supplied with `--user-uid`.
`capture_source` records the capture backend/source used for the export, such as
`npcap`, `libpcap`, `windows_packet`, or `mitmproxy_flows`.
