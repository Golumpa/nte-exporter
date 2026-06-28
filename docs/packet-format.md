# Packet Format Notes

This prototype supports separate Monopoly and Arc/Gashapon history decoders.

## Monopoly

- History is fetched over the UDP game connection.
- A client history-page request has a 45-byte request prefix. UDP payloads may
  contain additional coalesced transport data after that prefix.
- History request constant: `4220` / `0x107c`.
- Request selector `4`: `Lottery_Permanent`.
- Request selector `8`: `Lottery_LimitedCharacter`.
- Request page cursor: `page_number * 4`.
- Normal server responses contain 5 history records.
- The client can pipeline several page requests before responses arrive.
- Under load, one server response can contain multiple consecutive pages. The
  observed format contained 10 records representing two five-record pages,
  with an internal response header before the second page's first record.
- Some batched responses begin at a non-byte-aligned position in the UDP
  payload. The decoder tests all LSB bit offsets; captures have been observed
  where the record stream begins five bits into the byte stream.
- The final page may contain fewer than 5 records.

Decoded fields:

- `roll_result = first u32 / 4`
- `roll_result = 0` means Points Gift
- Some page-first records include a one-byte page prefix and an extra `0x14`
  field before the real dice u32. In that shape, the real dice u32 is at offset
  9 within the record chunk, not the earlier `0x14` field.
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

Pages are anchored to the continuous run starting at page 1 (history always loads page 1 first), so the newest timestamp group's ordinal 0 is always captured. Ordinals are assigned in scan order (newest first), so ordinal 0 of a timestamp group is its newest record and any unseen continuation rows can only append after the captured ones with higher ordinals. Every exported UID is therefore stable, including a partially captured oldest 10-pull, so all decoded rows are exported. If page 1 itself was not captured, the run falls back to the longest continuous block and emits `DID_NOT_START_AT_PAGE_1`.

## Arc / Gashapon

- Arc history uses a separate 34-byte request prefix and may likewise have
  coalesced transport data after it.
- Request constant: `2060` / `0x080c`.
- Cursor step: `2`.
- Pool: `Arc_MiracleBox`.
- Each response page normally contains 5 records.
- Arc timestamps use `unix_seconds = little_endian_u64(timestamp_raw) / 20000000 - 62135596800`.
- Arc pulls are treated as 10-pull timestamp groups. Like Monopoly, every captured group is exported, including the oldest one even if the scan stopped mid-10-pull (its captured prefix is ordinal-stable).
- Arc rows use the same `reward_type`, `reward_id`, `reward_name`, `reward_rank`, and `reward_key_hex` fields as Monopoly rows.
