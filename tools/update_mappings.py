from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nte_history_exporter.mapping_update import (  # noqa: E402
    DEFAULT_SOURCE_REF,
    MappingUpdateError,
    apply_update,
    build_mapping_update,
    load_assets,
    load_current_mappings,
    write_update,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronise reward mappings from the authoritative NTE_Assets tables."
    )
    parser.add_argument(
        "--assets-root",
        type=Path,
        help="local NTE_Assets checkout (downloads the required tables when omitted)",
    )
    parser.add_argument(
        "--source-ref",
        default=DEFAULT_SOURCE_REF,
        help="NTE_Assets branch, tag, or commit to download (default: main)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "build" / "mapping-update",
        help="directory for staged mappings and the review report",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="replace reward mapping files after staging and validation",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 when the generated snapshot differs from local mappings",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        assets = load_assets(assets_root=args.assets_root, source_ref=args.source_ref)
        current = load_current_mappings(ROOT / "mappings")
        result = build_mapping_update(current, assets)
        write_update(result, args.output_dir)
        if args.apply:
            apply_update(result, ROOT / "mappings")
    except (MappingUpdateError, OSError) as exc:
        print(f"mapping update failed: {exc}", file=sys.stderr)
        return 2

    changes = result.report["changes"]
    print(f"source: {assets.source}")
    if assets.source_ref:
        print(f"source ref: {assets.source_ref}")
    print(f"staged: {args.output_dir}")
    print(
        "changes: "
        f"{changes['additions']} additions, "
        f"{changes['updates']} updates, "
        f"{changes['deletions']} deletions"
    )
    if args.apply:
        print("applied: mappings/arcs.json, mappings/characters.json, mappings/items.json")
    return 1 if args.check and result.change_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
