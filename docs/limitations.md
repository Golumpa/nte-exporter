# Limitations

This is a prototype and supports `Lottery_Permanent`, `Lottery_LimitedCharacter`, `Arc_MiracleBox`, and `Gashapon_MysteryBox`.

Known limitations:

- Other NTE banners are not implemented yet.
- Mystery Box history does not expose a semantic rotation ID in each decoded row. The exporter deliberately keeps one unsplit history stream and leaves rotation grouping to consumers.
- The game appears not to provide a unique server-side roll ID in the decoded record body.
- UIDs are generated deterministically from decoded fields and timestamp-group order.
- A partially captured oldest timestamp group is still exported; its captured prefix has stable UIDs, and a later deeper scan adds the rest with the same UIDs.
- Pages are anchored to the continuous run starting at page 1. Live capture reports gaps immediately and accepts replacement pages from another pass while the exporter remains open. Scrolling backward does not request cached pages again, so close and reopen the history board before rescanning. Any gap left when capture ends causes later pages to be ignored and reported as warnings.
- Pipelined page requests and multi-page responses are supported, including observed 10-record responses containing two consecutive Monopoly pages. Non-byte-aligned response payloads are realigned before decoding.
- Structured Monopoly and Arc blocks are parsed in enrichment/fallback mode.
  The existing decoder remains authoritative when structured rows do not agree
  on record count, reward ID, and timestamp.
- Structured snapshot/segment assembly is limited to runs where every decoded
  row came from structured fallback. Existing primary-decoder runs are never
  reordered. Ambiguous generations retain the last proven snapshot.
- Live capture prefers Npcap on Windows and automatically falls back to the built-in raw-socket backend if Npcap is unavailable. Linux and macOS require the system libpcap runtime.
- The file adapter reads mitmproxy `.flows` captures for research and testing.
- Npcap is Windows-only and is not redistributed with this project; Linux and macOS use their system libpcap.
- Reward keys decode to their reward id string, so unknown rewards still export a usable `reward_id`; display names/ranks come from the mapping JSON files and should be expanded as new rewards appear.

Privacy guardrail: raw packet data must not be included in sanitized exports.
