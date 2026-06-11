from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from nte_history_exporter.decoder.boundary import select_continuous_run_from_page_1
from nte_history_exporter.decoder.arc import (
    arc_request_page,
    build_arc_rows_from_pairs,
    is_arc_history_request,
    parse_arc_response,
    select_continuous_arc_run,
)
from nte_history_exporter.decoder.protocol import (
    history_request_kind,
    is_history_request,
    request_page,
    response_contains_history_marker,
)
from nte_history_exporter.decoder.run import build_rows_from_pairs, fmt_packet_time


def parse_tnetstring(data: bytes, i: int = 0) -> tuple[Any, int]:
    j = data.find(b":", i)
    if j < 0:
        raise EOFError("no tnetstring length separator found")
    length = int(data[i:j])
    start = j + 1
    end = start + length
    payload = data[start:end]
    typ = chr(data[end])
    next_i = end + 1

    if typ in ",;":
        return payload, next_i
    if typ == "#":
        return int(payload), next_i
    if typ == "^":
        return float(payload), next_i
    if typ == "!":
        return payload == b"true", next_i
    if typ == "~":
        return None, next_i
    if typ == "]":
        arr = []
        k = 0
        while k < len(payload):
            value, k = parse_tnetstring(payload, k)
            arr.append(value)
        return arr, next_i
    if typ == "}":
        obj = {}
        k = 0
        while k < len(payload):
            key, k = parse_tnetstring(payload, k)
            value, k = parse_tnetstring(payload, k)
            obj[key] = value
        return obj, next_i
    raise ValueError(f"unknown tnetstring type {typ!r}")


def read_flows(path: str | Path) -> list[Any]:
    data = Path(path).read_bytes()
    i = 0
    flows = []
    while i < len(data):
        value, i = parse_tnetstring(data, i)
        flows.append(value)
    return flows


def find_udp_flow(flows: list[Any], preferred_index: int | None = None) -> tuple[int, Any]:
    if preferred_index is not None:
        return preferred_index, flows[preferred_index]
    candidates = []
    for idx, flow in enumerate(flows):
        if b"messages" not in flow:
            continue
        server = flow.get(b"server_conn", {})
        if server.get(b"transport_protocol") != b"udp":
            continue
        candidates.append((len(flow[b"messages"]), idx, flow))
    if not candidates:
        raise RuntimeError("no UDP flow with messages found")
    _, idx, flow = max(candidates)
    return idx, flow


def pair_response(messages: list[Any], request_index: int) -> tuple[int | None, bytes, float | None]:
    for j in range(request_index + 1, min(request_index + 50, len(messages))):
        from_client, content, ts = messages[j]
        if not from_client and len(content) >= 150 and response_contains_history_marker(content):
            return j, content, ts
    return None, b"", None


def pair_arc_response(messages: list[Any], request_index: int) -> tuple[int | None, bytes, float | None]:
    for j in range(request_index + 1, min(request_index + 30, len(messages))):
        from_client, content, ts = messages[j]
        if not from_client and len(content) >= 100 and parse_arc_response(content):
            return j, content, ts
    return None, b"", None


def decode_mitmproxy_flows(path: str | Path, flow_index: int | None = None) -> dict[str, Any]:
    flows = read_flows(path)
    resolved_flow_index, flow = find_udp_flow(flows, flow_index)
    messages = flow[b"messages"]

    pairs = []
    arc_pairs = []
    for i, msg in enumerate(messages):
        from_client, content, ts = msg
        if from_client and is_arc_history_request(content):
            page = arc_request_page(content)
            response_index, response_content, response_ts = pair_arc_response(messages, i)
            if response_index is not None:
                arc_pairs.append((page, page * 2, i, ts, response_index, response_ts, response_content))
            continue

        if not from_client or not is_history_request(content):
            continue
        kind = history_request_kind(content)
        offset = struct.unpack_from("<I", content, 31)[0]
        page = request_page(content)
        response_index, response_content, response_ts = pair_response(messages, i)
        if response_index is not None:
            pairs.append((page, offset, i, ts, response_index, response_ts, response_content, kind))

    best_run, run_warnings = select_continuous_run_from_page_1(pairs)
    rows_out = build_rows_from_pairs(best_run)
    best_arc_run, arc_warnings = select_continuous_arc_run(arc_pairs)
    arc_rows = build_arc_rows_from_pairs(best_arc_run)

    return {
        "flow_index": resolved_flow_index,
        "pairs": pairs,
        "best_run": best_run,
        "run_warnings": run_warnings,
        "rows": rows_out,
        "arc_pairs": arc_pairs,
        "best_arc_run": best_arc_run,
        "arc_rows": arc_rows,
        "arc_warnings": arc_warnings,
    }
