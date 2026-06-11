from __future__ import annotations

import json
import msvcrt
import socket
import time
from datetime import datetime
from pathlib import Path

from nte_history_exporter.constants import POOL_META
from nte_history_exporter.decoder.arc import arc_stability_warnings, select_continuous_arc_run
from nte_history_exporter.decoder.boundary import annotate_groups, page_gap_warnings
from nte_history_exporter.export.csv_export import write_csv
from nte_history_exporter.export.json_export import build_export_json
from nte_history_exporter.live_capture.session import LiveHistorySession, UdpPacket
from nte_history_exporter.live_capture.windows_raw import detect_local_ipv4, open_raw_udp_socket, read_packets


EXPORT_PREFIXES = {
    "permanent": "Permanent",
    "limited_character": "Limited",
    "arc_miracle_box": "Arc",
}


def copy_to_clipboard(text: str) -> None:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return
    except Exception:
        pass

    import subprocess

    subprocess.run(["clip"], input=text, text=True, check=True)


def run_live_capture(
    *,
    interface_ip: str | None = None,
    copy_clipboard: bool = True,
    write_debug_csv: bool = False,
) -> dict:
    local_ip = interface_ip or detect_local_ipv4()
    session = LiveHistorySession(local_ip)

    sock = open_raw_udp_socket(local_ip)
    print(f"Device 0 ready~! Listening on {local_ip}")
    print("Open either Monopoly history board. Capture will stay open until you press any key.")

    try:
        for packet in read_packets(sock):
            if msvcrt.kbhit():
                msvcrt.getch()
                break
            if packet is None:
                continue
            matched = session.process_packet(
                UdpPacket(
                    timestamp=time.time(),
                    src_ip=packet.src_ip,
                    dst_ip=packet.dst_ip,
                    src_port=packet.src_port,
                    dst_port=packet.dst_port,
                    payload=packet.payload,
                )
            )
            if matched:
                kind = session.pairs[-1][7] if session.pairs else "permanent"
                label = POOL_META.get(kind, POOL_META["permanent"])["name"]
                print(f"Captured {label} page {session.last_page_seen}")
    finally:
        try:
            sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
        except Exception:
            pass
        sock.close()

    exports = []
    for kind in session.kinds_seen():
        pairs = session.pairs_for_kind(kind)
        best_run = session.best_run(kind)
        rows = session.build_rows(kind)
        if kind == "arc_miracle_box":
            _arc_run, gap_warnings = select_continuous_arc_run(pairs)
            warnings = gap_warnings + arc_stability_warnings(rows)
        else:
            rows, warnings = annotate_groups(rows, starts_from_page_1=bool(best_run and best_run[0][0] == 1))
            warnings = page_gap_warnings(pairs, best_run) + warnings
        pages_seen = [p[0] for p in best_run]
        csv_path, json_path = export_paths(kind)
        if write_debug_csv:
            write_csv(csv_path, rows)
        export = build_export_json(
            rows,
            warnings,
            source="live_capture",
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

    if not exports:
        print("No Monopoly history pages were captured.")
        return {"exports": []}

    if copy_clipboard and len(exports) == 1:
        payload = exports[0]["payload"]
        copy_to_clipboard(payload)
        print("Export copied to clipboard.")
    elif len(exports) > 1:
        print("Multiple banners captured; clipboard copy skipped.")

    for item in exports:
        if item["csv_path"] is not None:
            print(f"CSV written: {item['csv_path']}")
        print(f"Export written: {item['json_path']}")
    return {"exports": exports}


def export_paths(kind: str) -> tuple[Path, Path]:
    export_dir = Path("exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    prefix = EXPORT_PREFIXES.get(kind, "History")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = export_dir / f"{prefix}_{stamp}"
    csv_path = base.with_suffix(".csv")
    json_path = base.with_suffix(".json")
    counter = 2
    while csv_path.exists() or json_path.exists():
        base = export_dir / f"{prefix}_{stamp}_{counter}"
        csv_path = base.with_suffix(".csv")
        json_path = base.with_suffix(".json")
        counter += 1
    return csv_path, json_path
