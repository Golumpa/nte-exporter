# Limitations

This is a prototype and supports `Lottery_Permanent`, `Lottery_LimitedCharacter`, and `Arc_MiracleBox`.

Known limitations:

- Other NTE banners are not implemented yet.
- The game appears not to provide a unique server-side roll ID in the decoded record body.
- UIDs are generated deterministically from decoded fields and timestamp-group order.
- Boundary timestamp groups may be skipped to avoid exporting unstable data.
- Page gaps are ignored outside the longest continuous run and reported as warnings.
- Live capture currently uses Windows raw sockets and requires administrator permission.
- The file adapter reads mitmproxy `.flows` captures for research and testing.
- The more stable and reliable Npcap/libpcap capture is not implemented yet.
- Reward keys decode to their reward id string, so unknown rewards still export a usable `reward_id`; display names/ranks come from the mapping JSON files and should be expanded as new rewards appear.

Privacy guardrail: raw packet data must not be included in sanitized exports.
