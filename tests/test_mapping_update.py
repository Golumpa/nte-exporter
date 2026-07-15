from __future__ import annotations

import json
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from nte_history_exporter.mapping_update import (
    MappingUpdateError,
    apply_update,
    build_mapping_update,
    load_assets,
    load_current_mappings,
    write_update,
)
from tests.support import FIXTURES


SAMPLE_ASSETS = FIXTURES / "nte_assets"


def sample_current():
    return {
        "arcs.json": {
            "fork_alpha": {"name": "Stale Alpha Name", "rank": "B"},
            "fork_retired": {"name": "Retired Arc", "rank": "A"},
        },
        "characters.json": {
            "1003": {"name": "Stale Character Name", "rank": "S"},
            "1001": {"name": "Retired Character", "rank": "A"},
        },
        "items.json": {
            "DiceNormal": {"type": "item", "name": "Fabricated Dice", "rank": "S"},
            "OldTicket": {"type": "item", "name": "Retired Ticket", "rank": "B"},
        },
    }


def build_sample_update():
    current = sample_current()
    return current, build_mapping_update(current, load_assets(assets_root=SAMPLE_ASSETS))


class MappingUpdateTests(unittest.TestCase):
    def test_mapping_update_is_an_authoritative_snapshot(self):
        current, result = build_sample_update()

        self.assertEqual(result.mappings["characters.json"]["1003"], {"name": "Old Character Renamed", "rank": "S"})
        self.assertEqual(result.mappings["characters.json"]["1099"], {"name": "New Character", "rank": "A"})
        self.assertNotIn("1001", result.mappings["characters.json"])
        self.assertNotIn("fork_retired", result.mappings["arcs.json"])
        self.assertNotIn("OldTicket", result.mappings["items.json"])
        self.assertNotEqual(result.mappings["characters.json"]["1003"], current["characters.json"]["1003"])
        self.assertEqual(result.report["changes"], {"additions": 4, "updates": 2, "deletions": 3})
        self.assertIs(result.report["safety"]["authoritative_snapshot"], True)
        self.assertIs(result.report["safety"]["deletions_allowed"], True)
        self.assertIs(result.report["safety"]["uid_inputs_touched"], False)
        self.assertIs(result.report["safety"]["pool_mappings_touched"], False)

    def test_items_use_illustrations_as_filter_and_asset_tables_as_authority(self):
        _current, result = build_sample_update()

        self.assertEqual(
            result.mappings["items.json"]["Fashion_Glide_2000"],
            {"type": "cosmetic", "name": "Inventory Glider", "rank": "A"},
        )
        self.assertIn("DiceNormal", result.mappings["items.json"])
        self.assertNotIn("DIceNormal", result.mappings["items.json"])
        self.assertNotIn("UnusedItem", result.mappings["items.json"])
        self.assertFalse(any(key.startswith("Characterawaken_") for key in result.mappings["items.json"]))

    def test_embedded_localized_strings_are_ignored(self):
        _current, result = build_sample_update()

        self.assertEqual(result.mappings["characters.json"]["1003"]["name"], "Old Character Renamed")
        self.assertNotEqual(result.mappings["characters.json"]["1003"]["name"], "Wrong Embedded Character")

    def test_mapping_update_rejects_missing_english_translation(self):
        assets = load_assets(assets_root=SAMPLE_ASSETS)
        tables = deepcopy(assets.tables)
        del tables["localization"]["ST_Player"]["character_1003"]

        with self.assertRaisesRegex(MappingUpdateError, "English localization is missing"):
            build_mapping_update(sample_current(), replace(assets, tables=tables))

    def test_mapping_update_rejects_ambiguous_translation_without_namespace_match(self):
        assets = load_assets(assets_root=SAMPLE_ASSETS)
        tables = deepcopy(assets.tables)
        tables["inventory"]["Fashion_glide_2000"]["ItemName"]["TableId"] = "/Game/Text/Unknown.Unknown"
        tables["localization"]["OtherNamespace"] = {"glider_2000": "Other Glider"}

        with self.assertRaisesRegex(MappingUpdateError, "is ambiguous"):
            build_mapping_update(sample_current(), replace(assets, tables=tables))

    def test_local_asset_source_has_reproducible_provenance(self):
        first = load_assets(assets_root=SAMPLE_ASSETS)
        second = load_assets(assets_root=SAMPLE_ASSETS)

        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.file_sha256, second.file_sha256)
        self.assertEqual(first.source, str(SAMPLE_ASSETS.resolve()))
        self.assertIsNone(first.source_ref)

    def test_mapping_update_writes_deterministic_review_artifacts(self):
        _current, result = build_sample_update()
        with TemporaryDirectory() as first_tmp, TemporaryDirectory() as second_tmp:
            first = Path(first_tmp)
            second = Path(second_tmp)
            write_update(result, first)
            write_update(result, second)

            for filename in (*result.mappings, "mapping-update-report.json"):
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())
            report = json.loads((first / "mapping-update-report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["changes"]["deletions"], 3)

    def test_mapping_update_does_not_mutate_inputs(self):
        current = sample_current()
        original = deepcopy(current)

        build_mapping_update(current, load_assets(assets_root=SAMPLE_ASSETS))

        self.assertEqual(current, original)

    def test_mapping_update_apply_touches_only_reward_mapping_files(self):
        _current, result = build_sample_update()
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for filename, mapping in sample_current().items():
                (directory / filename).write_text(json.dumps(mapping), encoding="utf-8")
            protected = directory / "permanent_board.json"
            protected.write_text('{"protected": true}\n', encoding="utf-8")

            apply_update(result, directory)

            self.assertEqual(load_current_mappings(directory), result.mappings)
            self.assertEqual(protected.read_text(encoding="utf-8"), '{"protected": true}\n')
            self.assertFalse((directory / "mapping-update-report.json").exists())

    def test_mapping_update_apply_rolls_back_partial_write(self):
        _current, result = build_sample_update()
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            originals = {}
            for filename, mapping in sample_current().items():
                destination = directory / filename
                destination.write_text(json.dumps(mapping), encoding="utf-8")
                originals[filename] = destination.read_bytes()

            from nte_history_exporter import mapping_update

            real_write = mapping_update._atomic_write
            calls = 0

            def fail_second_write(path, text):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("synthetic write failure")
                return real_write(path, text)

            with (
                patch("nte_history_exporter.mapping_update._atomic_write", side_effect=fail_second_write),
                self.assertRaisesRegex(OSError, "synthetic write failure"),
            ):
                apply_update(result, directory)

            for filename, original in originals.items():
                self.assertEqual((directory / filename).read_bytes(), original)

    def test_mapping_update_rejects_unresolved_illustrated_rewards(self):
        assets = load_assets(assets_root=SAMPLE_ASSETS)
        tables = deepcopy(assets.tables)
        tables["illustrations"]["MissingReward"] = {}

        with self.assertRaisesRegex(MappingUpdateError, "MissingReward"):
            build_mapping_update(sample_current(), replace(assets, tables=tables))

    def test_load_assets_rejects_missing_tables(self):
        with TemporaryDirectory() as tmp, self.assertRaisesRegex(MappingUpdateError, "cannot read"):
            load_assets(assets_root=Path(tmp))
