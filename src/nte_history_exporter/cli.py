from __future__ import annotations

import argparse
import json

from nte_history_exporter.adapters.mitmproxy_flows import decode_mitmproxy_flows
from nte_history_exporter.decoder.arc import arc_stability_warnings
from nte_history_exporter.decoder.boundary import annotate_groups, page_gap_warnings
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
    parser.add_argument(
        "--allow-boundary-records",
        action="store_true",
        help="Debug only: export boundary groups even when they may be partial.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.live or not args.capture_source:
        result = run_live_capture(
            interface_ip=args.interface_ip,
            copy_clipboard=not args.no_clipboard,
        )
        for item in result["exports"]:
            export = item["export"]
            print(
                "{banner}: decoded {decoded}, exported {exported}, skipped {skipped}.".format(
                    banner=export["banner"]["name"],
                    decoded=export["scan"]["decoded_records"],
                    exported=export["scan"]["exported_records"],
                    skipped=export["scan"]["skipped_records"],
                )
            )
            for warning in export["scan"]["warnings"]:
                suffix = f" ({warning['records']} records)" if "records" in warning else ""
                print(f"WARNING {warning['code']}: {warning['reason']}{suffix}")
        return 0

    decoded = decode_mitmproxy_flows(args.capture_source, args.flow_index)
    if decoded["arc_rows"] and not decoded["rows"]:
        rows = decoded["arc_rows"]
        warnings = decoded["arc_warnings"] + arc_stability_warnings(rows)
        kind = "arc_miracle_box"
        best_run = decoded["best_arc_run"]
        pair_count = len(decoded["arc_pairs"])
    else:
        rows, warnings = annotate_groups(
            decoded["rows"],
            starts_from_page_1=decoded["starts_from_page_1"],
            stable_only=not args.allow_boundary_records,
        )
        warnings = page_gap_warnings(decoded["pairs"], decoded["best_run"]) + warnings
        kind = decoded["best_run"][0][7] if decoded["best_run"] and len(decoded["best_run"][0]) > 7 else "permanent"
        best_run = decoded["best_run"]
        pair_count = len(decoded["pairs"])

    out_path, json_path = export_paths(kind)
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

    print(f"CSV written: {out_path}")
    print(f"JSON written: {json_path}")
    print(
        "Decoded {decoded}, exported {exported}, skipped {skipped}.".format(
            decoded=export["scan"]["decoded_records"],
            exported=export["scan"]["exported_records"],
            skipped=export["scan"]["skipped_records"],
        )
    )
    for warning in warnings:
        suffix = f" ({warning['records']} records)" if "records" in warning else ""
        print(f"WARNING {warning['code']}: {warning['reason']}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
