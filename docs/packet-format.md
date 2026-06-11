# Packet Format Notes

This prototype supports separate Monopoly and Arc/Gashapon history decoders.

## Monopoly

- History is fetched over the UDP game connection.
- Client history-page requests are 45 bytes.
- History request constant: `4220` / `0x107c`.
- Request selector `4`: `Lottery_Permanent`.
- Request selector `8`: `Lottery_LimitedCharacter`.
- Request page cursor: `page_number * 4`.
- Normal server responses contain 5 history records.
- The final page may contain fewer than 5 records.

Decoded fields:

- `roll_result = first u32 / 4`
- `roll_result = 0` means Points Gift
- Some page-first records have a short prefix before the record body. For these, a hidden signed source flag immediately after the visible dice field overrides the visible dice:
  - `source_flag = 0` means Points Gift
  - `source_flag = -4` means Chase Reward
- Timestamp is an 8-byte little-endian value
- `unix_seconds = little_endian_u64(timestamp_raw) / 40000000 - 62135596800`
- Reward keys are the reward id string encoded one character per byte as
  `ASCII * 4` with carry chaining into the next byte. The final byte is the
  pending carry (`00` or `01`) acting as a terminator, or is omitted.
  Examples: `98bdc9ad7dd9a5b99501` decodes to `fork_vine`,
  `10a58d9539bdc9b585b101` to `DiceNormal`, `c4c0cccc00` to character id `1033`.
  Arc/Gashapon history uses the same scheme at `ASCII * 2`.
- The decoder decodes the key to its id string and looks up display metadata
  in `mappings/arcs.json`, `mappings/characters.json`, and `mappings/items.json`.
  Unknown rewards still export their decoded id with empty name/rank.

Page and row numbers are research metadata only. They must not be used for permanent dedupe because they shift when new history appears.

Timestamp groups keep all records with the same raw timestamp together for UID ordinal generation. For boundary/group-size detection, only `result_type = dice` rows count as pull-set members; Points Gift and Chase Reward rows stay in the group but do not increase the dice-only group count.

Oldest-boundary groups are exported when their dice-only count is a positive multiple of 10: the pull set is provably finished, and any unseen same-timestamp continuation rows can only be non-dice tails that sort after the seen rows, so exported ordinals and UIDs stay stable. Oldest groups with other dice counts are still dropped unless the capture reached the true end of history. Newest-boundary groups remain positional-only: when a scan starts mid-history, unseen newer rows would shift ordinals, so dice count is never accepted as proof there.

## Arc / Gashapon

- Arc history uses a separate 34-byte request.
- Request constant: `2060` / `0x080c`.
- Cursor step: `2`.
- Pool: `Arc_MiracleBox`.
- Each response page normally contains 5 records.
- Arc timestamps use `unix_seconds = little_endian_u64(timestamp_raw) / 20000000 - 62135596800`.
- Arc pulls are treated as 10-pull timestamp groups; incomplete groups are skipped by default.
- Arc rows use the same `reward_type`, `reward_id`, `reward_name`, `reward_rank`, and `reward_key_hex` fields as Monopoly rows.
