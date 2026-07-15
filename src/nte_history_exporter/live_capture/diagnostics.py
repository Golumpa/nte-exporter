from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DIAGNOSTIC_FORMAT = "nte-capture-diagnostics"
DIAGNOSTIC_FORMAT_VERSION = 1
MAX_EVENTS = 200


class CaptureDiagnostics:
    """Collect bounded, privacy-safe observations about a capture session."""

    def __init__(self) -> None:
        self.counters: Counter[str] = Counter()
        self.event_counts: Counter[str] = Counter()
        self.reason_counts: Counter[str] = Counter()
        self.events: list[dict[str, Any]] = []

    def observe_packet(self, protocol: str) -> None:
        self.counters["packets_seen"] += 1
        if protocol == "udp":
            self.counters["udp_packets_seen"] += 1
        else:
            self.counters["non_udp_packets_ignored"] += 1

    def add_event(
        self,
        code: str,
        packet_index: int,
        *,
        reason: bool = False,
        **fields: Any,
    ) -> None:
        self.event_counts[code] += 1
        if reason:
            self.reason_counts[code] += 1
        if len(self.events) >= MAX_EVENTS:
            self.counters["events_omitted"] += 1
            return
        event: dict[str, Any] = {"packet_index": packet_index, "code": code}
        event.update({key: value for key, value in fields.items() if value is not None})
        self.events.append(event)

    def report(self, pending_requests: Iterable[Any]) -> dict[str, Any]:
        pending = [
            {
                "kind": request.kind,
                "page": request.page,
                "response_candidates": request.response_candidates,
                "response_candidate_lengths": list(request.response_candidate_lengths),
            }
            for request in pending_requests
        ]
        return {
            "format": DIAGNOSTIC_FORMAT,
            "format_version": DIAGNOSTIC_FORMAT_VERSION,
            "privacy": {
                "contains_network_addresses": False,
                "contains_network_ports": False,
                "contains_packet_timestamps": False,
                "contains_payload_bytes": False,
                "contains_user_uid": False,
            },
            "counters": dict(sorted(self.counters.items())),
            "event_counts": dict(sorted(self.event_counts.items())),
            "reason_counts": dict(sorted(self.reason_counts.items())),
            "events": list(self.events),
            "pending_requests": pending,
        }


def new_diagnostics_path(output_dir: str | Path = "exports") -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = directory / f"Capture_{stamp}.diagnostics.json"
    counter = 2
    while path.exists():
        path = directory / f"Capture_{stamp}_{counter}.diagnostics.json"
        counter += 1
    return path


def write_capture_diagnostics(path: str | Path, report: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
