# Capture diagnostics

Running the exporter with `--debug` writes a UID-free `Capture_*.diagnostics.json`
file in the export directory. This sidecar explains what the capture
pipeline recognized, rejected, and paired without changing the public export
format or record order. It is also written when no history page could be
exported.

The report contains bounded events, aggregate counters, reason codes, packet
positions, payload lengths, history kinds, page numbers, and record counts. It
does not contain packet payloads, IP addresses, ports, packet timestamps, or a
user UID. The report format is versioned independently as
`nte-capture-diagnostics` version 1.

Useful rejection codes include:

- `RESPONSE_TOO_SHORT`: a matching inbound packet could not contain a history
  response;
- `NO_HISTORY_MARKER`: a matching response candidate had no known history
  marker;
- `HISTORY_MARKER_PARSE_FAILED`: a known marker was present but neither decoder
  produced records;
- `RESPONSE_KIND_MISMATCH`: decoded data did not match the pending history kind;
- `REQUEST_REPLACED`: a recovery request superseded an unanswered request.

Events are capped at 200 per session. Aggregate counters continue after that
limit and `events_omitted` records how many event entries were left out.
