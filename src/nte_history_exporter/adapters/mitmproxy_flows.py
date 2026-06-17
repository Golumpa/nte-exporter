from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from nte_history_exporter.decoder.boundary import select_continuous_run_from_page_1
from nte_history_exporter.decoder.arc import build_arc_rows_from_pairs, select_continuous_arc_run
from nte_history_exporter.decoder.run import build_rows_from_pairs
from nte_history_exporter.decoder.user_uid import extract_user_uid_candidates
from nte_history_exporter.live_capture.session import LiveHistorySession, UdpPacket


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


def decode_mitmproxy_flows(path: str | Path, flow_index: int | None = None) -> dict[str, Any]:
    flows = read_flows(path)
    user_uid_candidates: Counter[str] = Counter()
    for flow in flows:
        for msg in flow.get(b"messages", []):
            user_uid_candidates.update(extract_user_uid_candidates(msg[1]))
    user_uid = user_uid_candidates.most_common(1)[0][0] if user_uid_candidates else None

    resolved_flow_index, flow = find_udp_flow(flows, flow_index)
    messages = flow[b"messages"]

    local_ip = "192.0.2.1"
    remote_ip = "198.51.100.1"
    local_port = 50000
    remote_port = 40000
    session = LiveHistorySession(local_ip)
    for msg in messages:
        from_client, content, ts = msg
        if from_client:
            packet = UdpPacket(ts, local_ip, remote_ip, local_port, remote_port, content)
        else:
            packet = UdpPacket(ts, remote_ip, local_ip, remote_port, local_port, content)
        session.process_packet(packet)

    pairs = [pair for pair in session.pairs if pair[7] != "arc_miracle_box"]
    arc_pairs = [pair for pair in session.pairs if pair[7] == "arc_miracle_box"]
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
        "user_uid": session.user_uid or user_uid,
    }
