from __future__ import annotations

import argparse
import json

from nte_history_exporter import console
from nte_history_exporter.adapters.mitmproxy_flows import decode_mitmproxy_flows
from nte_history_exporter.decoder.boundary import annotate_groups
from nte_history_exporter.export.csv_export import write_csv
from nte_history_exporter.export.json_export import build_export_json
from nte_history_exporter.live_capture.libpcap import LibpcapUnavailable
from nte_history_exporter.live_capture.runner import export_paths, run_live_capture


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decode NTE pull history from mitmproxy .flows captures or live capture."
    )
    parser.add_argument("capture_source", nargs="?", help="mitmproxy .flows file; omit when using --live")
    parser.add_argument("--live", action="store_true", help="capture live UDP traffic instead of reading a .flows file")
    parser.add_argument("--flow-index", type=int, default=None)
    parser.add_argument("--interface-ip", default=None, help="local IPv4 address to bind for live capture")
    parser.add_argument(
        "--capture-backend",
        choices=["auto", "libpcap", "raw"],
        default="auto",
        help=(
            "live capture backend; auto prefers Npcap/libpcap and falls back to raw sockets on Windows "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument("--copy-clipboard", action="store_true", help="copy a single live export to clipboard")
    parser.add_argument("--debug", action="store_true", help="also write research CSVs next to the JSON exports")
    parser.add_argument("--user-uid", default=None, help="override the auto-detected NTE user UID in the JSON export")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console.print_banner()
    if args.live or not args.capture_source:
        try:
            run_live_capture(
                interface_ip=args.interface_ip,
                capture_backend=args.capture_backend,
                copy_clipboard=args.copy_clipboard,
                write_debug_csv=args.debug,
                user_uid=args.user_uid,
            )
            return 0
        except (LibpcapUnavailable, PermissionError) as exc:
            console.print_problem(str(exc))
            console.print_note("Install/enable Npcap or libpcap and run with packet-capture permissions.")
            return 1

    decoded = decode_mitmproxy_flows(args.capture_source, args.flow_index)
    if decoded["arc_rows"] and not decoded["rows"]:
        rows = decoded["arc_rows"]
        warnings = decoded["arc_warnings"]
        kind = "arc_miracle_box"
        best_run = decoded["best_arc_run"]
        pair_count = len(decoded["arc_pairs"])
    else:
        rows = annotate_groups(decoded["rows"])
        warnings = decoded["run_warnings"]
        kind = decoded["best_run"][0][7] if decoded["best_run"] and len(decoded["best_run"][0]) > 7 else "permanent"
        best_run = decoded["best_run"]
        pair_count = len(decoded["pairs"])

    resolved_user_uid = args.user_uid or decoded.get("user_uid")
    if not resolved_user_uid:
        resolved_user_uid = console.prompt_user_uid()

    out_path, json_path = export_paths(kind, resolved_user_uid)
    if args.debug:
        write_csv(out_path, rows)
    export = build_export_json(
        rows,
        warnings,
        source="packet_capture",
        capture_source="mitmproxy_flows",
        user_uid=resolved_user_uid,
        flow_index=decoded["flow_index"],
        candidate_request_response_pairs=pair_count,
        pages_seen=[p[0] for p in best_run],
    )
    json_path.write_text(json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")

    console.print_results_header()
    console.print_export_summary(
        export["banner"]["name"],
        export["scan"]["decoded_records"],
        export["scan"]["exported_records"],
        export["scan"]["skipped_records"],
    )
    for warning in warnings:
        console.print_warning(warning["code"], warning["reason"], warning.get("records"))
    print()
    if args.debug:
        console.print_note(f"CSV written: {out_path}")
    console.print_note(f"Export written: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
