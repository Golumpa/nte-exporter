from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from nte_history_exporter import console
from nte_history_exporter.constants import POOL_META
from nte_history_exporter.decoder.boundary import annotate_groups, select_continuous_run_from_page_1
from nte_history_exporter.export.csv_export import write_csv
from nte_history_exporter.export.json_export import build_export_json
from nte_history_exporter.live_capture.backends import open_capture_backend
from nte_history_exporter.live_capture.session import LiveHistorySession, UdpPacket
from nte_history_exporter.live_capture.stop_key import StopKeyMonitor
from nte_history_exporter.live_capture.windows_raw import detect_local_ipv4


EXPORT_PREFIXES = {
    "permanent": "Permanent",
    "limited_character": "Limited",
    "arc_miracle_box": "Arc",
}

CAPTURE_SOURCE_LABELS = {
    "windows_raw": "windows_packet",
}


def copy_to_clipboard(text: str) -> bool:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        pass

    commands = []
    if sys.platform == "win32":
        commands.append(["clip"])
    elif sys.platform == "darwin":
        commands.append(["pbcopy"])
    else:
        commands.extend([["wl-copy"], ["xclip", "-selection", "clipboard"]])

    for command in commands:
        try:
            subprocess.run(command, input=text, text=True, check=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return False


def run_live_capture(
    *,
    interface_ip: str | None = None,
    capture_backend: str = "auto",
    copy_clipboard: bool = False,
    write_debug_csv: bool = False,
    user_uid: str | None = None,
) -> dict:
    local_ip = interface_ip or detect_local_ipv4()
    session = LiveHistorySession(local_ip)

    capture = open_capture_backend(local_ip, capture_backend)
    console.print_live_instructions(local_ip, capture.name, capture.detail)
    if capture.fallback_reason:
        console.print_capture_fallback(capture.fallback_reason)
    reported_missing_pages: dict[str, tuple[int, ...]] = {}

    try:
        with StopKeyMonitor() as stop_key:
            for packet in capture.packets():
                if stop_key.pressed():
                    break
                if packet is None:
                    continue
                pair_count_before = len(session.pairs)
                matched = session.process_packet(
                    UdpPacket(
                        timestamp=time.time(),
                        src_ip=packet.src_ip,
                        dst_ip=packet.dst_ip,
                        src_port=packet.src_port,
                        dst_port=packet.dst_port,
                        payload=packet.payload,
                        protocol=packet.protocol,
                    )
                )
                if matched:
                    affected_kinds = []
                    for pair in session.pairs[pair_count_before:]:
                        page = pair[0]
                        kind = pair[7] if len(pair) > 7 else "permanent"
                        label = POOL_META.get(kind, POOL_META["permanent"])["name"]
                        was_replacement = any(
                            existing[0] == page
                            and (existing[7] if len(existing) > 7 else "permanent") == kind
                            for existing in session.pairs[:pair_count_before]
                        )
                        console.print_page_captured(label, page, recaptured=was_replacement)
                        if kind not in affected_kinds:
                            affected_kinds.append(kind)

                    for kind in affected_kinds:
                        label = POOL_META.get(kind, POOL_META["permanent"])["name"]
                        missing_pages = tuple(session.missing_pages(kind))
                        previously_missing = reported_missing_pages.get(kind, ())
                        if missing_pages and missing_pages != previously_missing:
                            reasons = {
                                page: session.missing_page_reason(kind, page)
                                for page in missing_pages
                            }
                            console.print_missing_pages(label, list(missing_pages), reasons)
                        elif previously_missing and not missing_pages:
                            console.print_page_gap_recovered(label)
                        reported_missing_pages[kind] = missing_pages
    finally:
        stats = capture.stats()
        capture.close()

    if stats:
        console.print_capture_stats(
            stats.received,
            stats.dropped,
            stats.interface_dropped,
        )

    exports = []
    resolved_user_uid = user_uid or session.user_uid
    if session.kinds_seen() and not resolved_user_uid:
        resolved_user_uid = console.prompt_user_uid()
    capture_source = CAPTURE_SOURCE_LABELS.get(capture.name, capture.name)
    for kind in session.kinds_seen():
        pairs = session.pairs_for_kind(kind)
        best_run, run_warnings = select_continuous_run_from_page_1(pairs)
        rows = session.build_rows(kind)
        if kind != "arc_miracle_box":
            rows = annotate_groups(rows)
        warnings = run_warnings
        pages_seen = [p[0] for p in best_run]
        csv_path, json_path = export_paths(kind, resolved_user_uid)
        if write_debug_csv:
            write_csv(csv_path, rows)
        export = build_export_json(
            rows,
            warnings,
            source="live_capture",
            capture_source=capture_source,
            user_uid=resolved_user_uid,
            pages_seen=pages_seen,
        )
        payload = json.dumps(export, ensure_ascii=False, indent=2)
        json_path.write_text(payload, encoding="utf-8")
        exports.append(
            {
                "kind": kind,
                "csv_path": csv_path if write_debug_csv else None,
                "json_path": json_path,
                "export": export,
                "payload": payload,
            }
        )

    console.print_results_header()
    if not exports:
        console.print_problem("No history pages were captured.")
        console.print_note("Make sure the capture backend is running, then reopen the")
        console.print_note("history screen and scroll from page 1. If no page messages")
        console.print_note("appear, return to the main menu and re-enter the game.")
        return {"exports": []}

    for item in exports:
        scan = item["export"]["scan"]
        console.print_export_summary(
            item["export"]["banner"]["name"],
            scan["decoded_records"],
            scan["exported_records"],
            scan["skipped_records"],
        )
        for warning in scan["warnings"]:
            console.print_warning(warning["code"], warning["reason"], warning.get("records"))

    print()
    for item in exports:
        if item["csv_path"] is not None:
            console.print_note(f"CSV written: {item['csv_path']}")
        console.print_note(f"Export written: {item['json_path']}")

    if copy_clipboard and len(exports) == 1:
        if copy_to_clipboard(exports[0]["payload"]):
            console.print_success("Export copied to clipboard - paste it straight into your tracker.")
        else:
            console.print_note("Clipboard tool unavailable; use the JSON file shown above.")
    elif copy_clipboard and len(exports) > 1:
        console.print_note("Multiple banners captured; clipboard copy skipped so one export")
        console.print_note("does not overwrite another.")
    return {"exports": exports}


def export_paths(kind: str, user_uid: str | None = None) -> tuple[Path, Path]:
    export_dir = Path("exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    prefix = EXPORT_PREFIXES.get(kind, "History")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid_prefix = _safe_filename_part(user_uid) if user_uid else "unknown"
    base_name = f"{uid_prefix}_{prefix}_{stamp}"
    base = export_dir / base_name
    csv_path = base.with_suffix(".csv")
    json_path = base.with_suffix(".json")
    counter = 2
    while csv_path.exists() or json_path.exists():
        base = export_dir / f"{base_name}_{counter}"
        csv_path = base.with_suffix(".csv")
        json_path = base.with_suffix(".json")
        counter += 1
    return csv_path, json_path


def _safe_filename_part(value: str | None) -> str:
    if not value:
        return "unknown"
    cleaned = "".join(ch for ch in value.strip() if ch.isalnum() or ch in ("-", "_"))
    return cleaned or "unknown"
