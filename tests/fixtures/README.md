# Synthetic network fixture

`synthetic_history_network.json` is the committed end-to-end packet fixture for
the exporter test suite. It contains UDP payloads for Permanent Board and Arc
history requests/responses, plus isolated protocol edge cases.

The fixture is safe to publish:

- endpoints use the RFC 5737 documentation ranges `192.0.2.0/24` and
  `198.51.100.0/24`;
- packet and history timestamps are deterministic synthetic values;
- it contains no game user UID, account/session data, cookies, tokens, or raw
  capture metadata;
- the test suite checks every payload with the UID extractor before accepting
  it.

Tests load the fixture through helpers in `tests/support.py`. The `replay`
scenario is fed through `LiveHistorySession`; `protocol_sample` packets cover
points gifts, chase rewards, batched pages, and bit-packed responses.

Do not replace this file with a real `.pcap`, `.flows`, or exported account
history. Add new cases by constructing the smallest relevant payload, replacing
all timestamps and endpoints, and extending the privacy assertions.

## Synthetic NTE_Assets fixture

`nte_assets/` mirrors only the six table paths and English localization file
consumed by the mapping updater. Its rows, IDs, and names are deliberately
synthetic and contain no account or personal data. The fixture exercises
authoritative additions, metadata updates, deletions, translation lookup,
illustration filtering, and canonical ID casing without depending on the
network or copying a live game-data snapshot into the repository.
