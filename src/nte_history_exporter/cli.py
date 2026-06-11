from __future__ import annotations

import argparse
import json

from nte_history_exporter import console
from nte_history_exporter.adapters.mitmproxy_flows import decode_mitmproxy_flows
from nte_history_exporter.decoder.arc import arc_stability_warnings
from nte_history_exporter.decoder.boundary import annotate_groups
from nte_history_exporter.export.csv_export import write_csv
from nte_history_exporter.export.json_export import build_export_json
from nte_history_exporter.live_capture.runner import export_paths, run_live_capture


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decode NTE Monopoly history from mitmproxy .flows captures or live capture."
    )
    parser.add_argument("capture_source", nargs="?", help="mitmproxy .flows file; omit when using --live")
    parser.add_argument("--live", action="store_true", help="capture live UDP traffic instead of reading a .flows file")
    parser.add_argument("--flow-index", type=int, default=None)
    parser.add_argument("--interface-ip", default=None, help="local IPv4 address to bind for live capture")
    parser.add_argument("--no-clipboard", action="store_true", help="do not copy live exports to clipboard")
    parser.add_argument("--debug", action="store_true", help="also write research CSVs next to the JSON exports")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console.print_banner()
    if args.live or not args.capture_source:
        run_live_capture(
            interface_ip=args.interface_ip,
            copy_clipboard=not args.no_clipboard,
            write_debug_csv=args.debug,
        )
        return 0

    decoded = decode_mitmproxy_flows(args.capture_source, args.flow_index)
    if decoded["arc_rows"] and not decoded["rows"]:
        rows = decoded["arc_rows"]
        warnings = decoded["arc_warnings"] + arc_stability_warnings(rows)
        kind = "arc_miracle_box"
        best_run = decoded["best_arc_run"]
        pair_count = len(decoded["arc_pairs"])
    else:
        rows, group_warnings = annotate_groups(decoded["rows"])
        warnings = decoded["run_warnings"] + group_warnings
        kind = decoded["best_run"][0][7] if decoded["best_run"] and len(decoded["best_run"][0]) > 7 else "permanent"
        best_run = decoded["best_run"]
        pair_count = len(decoded["pairs"])

    out_path, json_path = export_paths(kind)
    if args.debug:
        write_csv(out_path, rows)
    export = build_export_json(
        rows,
        warnings,
        source="packet_capture",
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
    console.maybe_print_incomplete_hint(warnings)
    print()
    if args.debug:
        console.print_note(f"CSV written: {out_path}")
    console.print_note(f"Export written: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
