import csv
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EXPORTS = ROOT / "exports"
V7_EXPORTS = EXPORTS / "1"
ARC_EXPORTS = EXPORTS / "arc"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nte_history_exporter.decoder.boundary import annotate_groups, make_uid
from nte_history_exporter.constants import LIMITED_CHARACTER_MARKER, MARKER
from nte_history_exporter.decoder.boundary import select_continuous_run_from_page_1
from nte_history_exporter.decoder.protocol import decode_response_records, history_request_kind
from nte_history_exporter.constants import POOL_META
from nte_history_exporter.mappings import ARC_META, CHARACTERS, ITEMS, REWARDS_BY_ID
from nte_history_exporter.decoder.protocol import decode_reward_key, infer_reward_type
from nte_history_exporter.decoder.user_uid import extract_user_uid
from nte_history_exporter.decoder.arc import (
    arc_request_page,
    build_arc_rows_from_pairs,
    decode_arc_key,
    decode_arc_timestamp,
    is_arc_history_request,
    make_arc_uid,
    parse_arc_response,
)
from nte_history_exporter.live_capture.session import LiveHistorySession, UdpPacket
from nte_history_exporter.live_capture.libpcap import (
    DLT_EN10MB,
    DLT_LINUX_SLL,
    DLT_LINUX_SLL2,
    DLT_LOOP,
    DLT_RAW,
    _extract_ipv4_frame,
    _load_library,
    LibpcapUnavailable,
)
from nte_history_exporter.live_capture.windows_raw import parse_ipv4_packet
from nte_history_exporter.live_capture.backends import open_capture_backend
from nte_history_exporter.export.json_export import build_export_json
from nte_history_exporter.live_capture.runner import export_paths
from nte_history_exporter.pool_mappings import load_pool_mappings, pool_meta_from_mapping


def load_reference_csv(name):
    path = EXPORTS / name
    if not path.exists():
        path = EXPORTS / "old" / name
    if not path.exists():
        raise unittest.SkipTest(f"private reference fixture not present: {path}")
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            normalized = dict(row)
            for key in ["page", "offset", "row", "dice", "dice_raw_u32", "quantity"]:
                if normalized.get(key) not in ("", None):
                    normalized[key] = int(normalized[key])
            rows.append(normalized)
    return rows


def decode_single_record(record_hex):
    return decode_response_records(bytes(0x50) + bytes.fromhex(record_hex))[0]


def load_v7_row(name, one_based_index):
    path = V7_EXPORTS / name
    if not path.exists():
        raise unittest.SkipTest(f"private reference fixture not present: {path}")
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[one_based_index - 1]


def load_arc_csv(name):
    path = ARC_EXPORTS / name
    if not path.exists():
        raise unittest.SkipTest(f"private reference fixture not present: {path}")
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class BoundaryExportTests(unittest.TestCase):
    def test_windows_auto_prefers_npcap(self):
        capture = Mock(device=r"\Device\NPF_test")
        with (
            patch("nte_history_exporter.live_capture.backends.sys.platform", "win32"),
            patch(
                "nte_history_exporter.live_capture.backends.open_libpcap_capture",
                return_value=capture,
            ),
            patch("nte_history_exporter.live_capture.backends.RawSocketCapture") as raw_capture,
        ):
            selected = open_capture_backend("192.0.2.1")

        self.assertIs(selected, capture)
        self.assertEqual(selected.name, "npcap")
        self.assertEqual(selected.fallback_reason, "")
        raw_capture.assert_not_called()

    def test_windows_auto_falls_back_to_raw_socket_without_npcap(self):
        fallback = Mock()
        with (
            patch("nte_history_exporter.live_capture.backends.sys.platform", "win32"),
            patch(
                "nte_history_exporter.live_capture.backends.open_libpcap_capture",
                side_effect=LibpcapUnavailable("Npcap could not be loaded"),
            ),
            patch(
                "nte_history_exporter.live_capture.backends.RawSocketCapture",
                return_value=fallback,
            ) as raw_capture,
        ):
            selected = open_capture_backend("192.0.2.1")

        self.assertIs(selected, fallback)
        raw_capture.assert_called_once_with(
            "192.0.2.1",
            fallback_reason="Npcap could not be loaded",
        )

    def test_explicit_libpcap_does_not_fall_back(self):
        with (
            patch("nte_history_exporter.live_capture.backends.sys.platform", "win32"),
            patch(
                "nte_history_exporter.live_capture.backends.open_libpcap_capture",
                side_effect=LibpcapUnavailable("Npcap could not be loaded"),
            ),
            patch("nte_history_exporter.live_capture.backends.RawSocketCapture") as raw_capture,
            self.assertRaises(LibpcapUnavailable),
        ):
            open_capture_backend("192.0.2.1", "libpcap")

        raw_capture.assert_not_called()

    def test_windows_libpcap_load_prefers_system_then_path(self):
        system_dir = Path("C:/Windows/System32/Npcap")
        loaded = Mock()
        with (
            patch("nte_history_exporter.live_capture.libpcap.sys.platform", "win32"),
            patch("nte_history_exporter.live_capture.libpcap._windows_npcap_directory", return_value=system_dir),
            patch("nte_history_exporter.live_capture.libpcap.Path.is_dir", return_value=True),
            patch("nte_history_exporter.live_capture.libpcap.os.add_dll_directory", return_value=Mock(), create=True),
            patch(
                "nte_history_exporter.live_capture.libpcap.ctypes.CDLL",
                side_effect=[OSError("system missing"), loaded],
            ) as cdll,
        ):
            self.assertIs(_load_library(), loaded)

        self.assertEqual(
            [call.args[0] for call in cdll.call_args_list],
            [
                str(system_dir / "wpcap.dll"),
                "wpcap.dll",
            ],
        )

    def test_libpcap_link_layers_extract_ipv4_packets(self):
        ip_packet = bytes.fromhex("4500001c0000000040110000c0000201c6336402") + bytes(8)
        ethernet = bytes(12) + bytes.fromhex("0800") + ip_packet
        loop = (2).to_bytes(4, sys.byteorder) + ip_packet
        linux_sll = bytes(14) + bytes.fromhex("0800") + ip_packet
        linux_sll2 = bytes.fromhex("0800") + bytes(18) + ip_packet

        self.assertEqual(_extract_ipv4_frame(ethernet, DLT_EN10MB), ip_packet)
        self.assertEqual(_extract_ipv4_frame(ip_packet, DLT_RAW), ip_packet)
        self.assertEqual(_extract_ipv4_frame(loop, DLT_LOOP), ip_packet)
        self.assertEqual(_extract_ipv4_frame(linux_sll, DLT_LINUX_SLL), ip_packet)
        self.assertEqual(_extract_ipv4_frame(linux_sll2, DLT_LINUX_SLL2), ip_packet)

    def test_pool_mapping_json_files_have_uniform_shape(self):
        required_top_level = {"pool_key", "game", "system", "banner", "request", "response"}
        for pool_key, mapping in load_pool_mappings().items():
            with self.subTest(pool_key=pool_key):
                self.assertEqual(set(required_top_level) - set(mapping), set())
                self.assertEqual(mapping["pool_key"], pool_key)
                self.assertIn("id", mapping["system"])
                self.assertIn("name", mapping["system"])
                self.assertIn("id", mapping["banner"])
                self.assertIn("name", mapping["banner"])
                self.assertIn("shared_pity", mapping["banner"])
                self.assertIn("family", mapping["request"])
                self.assertIn("length", mapping["request"])
                self.assertIn("constant", mapping["request"])
                self.assertIn("cursor_step", mapping["request"])

    def test_pool_mapping_json_matches_runtime_pool_meta(self):
        for pool_key, mapping in load_pool_mappings().items():
            with self.subTest(pool_key=pool_key):
                self.assertEqual(pool_meta_from_mapping(mapping), POOL_META[pool_key])

    def test_reward_mapping_files_have_expected_shape(self):
        self.assertTrue(ARC_META)
        for arc_id, meta in ARC_META.items():
            with self.subTest(arc_id=arc_id):
                self.assertTrue(arc_id.startswith("fork_"))
                self.assertIn("name", meta)
                self.assertIn(meta.get("rank"), ("S", "A", "B"))

        self.assertTrue(CHARACTERS)
        for character_id, info in CHARACTERS.items():
            with self.subTest(character_id=character_id):
                self.assertTrue(character_id.isdigit())
                self.assertIn("name", info)
                self.assertIn(info.get("rank"), ("S", "A"))

        self.assertTrue(ITEMS)
        for item_id, info in ITEMS.items():
            with self.subTest(item_id=item_id):
                self.assertIn(info.get("type"), ("item", "cosmetic"))
                self.assertIn("name", info)

    def test_rewards_by_id_merges_all_mapping_files(self):
        for reward_id in (*ARC_META, *CHARACTERS, *ITEMS):
            with self.subTest(reward_id=reward_id):
                reward = REWARDS_BY_ID[reward_id]
                self.assertEqual(reward["id"], reward_id)
                self.assertIn(reward["type"], ("arc", "character", "item", "cosmetic"))

    def test_decode_reward_key_round_trips_observed_keys(self):
        observed = {
            "98bdc9ad7dd9a5b99501": "fork_vine",
            "98bdc9ad7d41c9bdad85c9e5bdb901": "fork_Prokaryon",
            "98bdc9ad7ddda1d585add585b99d01": "fork_whuakuang",
            "98bdc9ad7dddd5a1d585add585b99d01": "fork_wuhuakuang",
            "10a58d9539bdc9b585b101": "DiceNormal",
            "10a58d957dd1a58dad95d17dc1c400": "Dice_ticket_01",
            "10a58d957dd1a58dad95d17dc1c800": "Dice_ticket_02",
            "10a58d95b1a5b5a5d19501": "Dicelimite",
            "1885cda1a5bdb97d1db1a591957dc5c0c4c000": "Fashion_Glide_1010",
            "1885cda1a5bdb97dd995a1a58db1957dc5c0c4c07c59c1c0e000": "Fashion_vehicle_1010_V008",
            "c4c0cccc00": "1033",
            "c4c0dcc000": "1070",
            "c4c0dcc0": "1070",
            "c4c0c8c4": "1021",
        }
        for key_hex, expected_id in observed.items():
            with self.subTest(key_hex=key_hex):
                self.assertEqual(decode_reward_key(bytes.fromhex(key_hex)), expected_id)

    def test_infer_reward_type_for_unmapped_ids(self):
        self.assertEqual(infer_reward_type("fork_newarc"), "arc")
        self.assertEqual(infer_reward_type("1099"), "character")
        self.assertEqual(infer_reward_type("Fashion_hat_2000"), "cosmetic")
        self.assertEqual(infer_reward_type("Dice_ticket_03"), "item")
        self.assertEqual(infer_reward_type(""), "")

    def test_uid_source_matches_v4_reference(self):
        rows = load_reference_csv("monopoly_history_poc_10_all_44_pages_v4.csv")
        first = rows[0]
        self.assertEqual(make_uid(first, 0), "5adcf52282e15445466863b271f3b745")

    def test_uid_uses_detected_pool_group_id(self):
        row = {
            "pool_group_id": "Lottery_LimitedCharacter",
            "timestamp_raw_hex": "40e93247c3097b23",
            "dice": 5,
            "reward_key_hex": "10a58d957dd1a58dad95d17dc1c800",
            "quantity": 50,
        }
        self.assertNotEqual(make_uid(row, 0), "5adcf52282e15445466863b271f3b745")

    def test_pages_1_to_5_exports_every_row(self):
        rows = load_reference_csv("monopoly_history_poc_13_pages_1_to_5_v4.csv")
        annotated = annotate_groups(rows)

        exported = [row for row in annotated if row["export_record"] is True]

        # Every decoded row is exported; boundary groups are never dropped.
        self.assertEqual(len(annotated), 25)
        self.assertEqual(len(exported), 25)

    @staticmethod
    def _synthetic_row(page, timestamp_hex, result_type):
        return {
            "page": page,
            "timestamp_raw_hex": timestamp_hex,
            "timestamp_decoded": f"ts-{timestamp_hex}",
            "result_type": result_type,
            "dice": 4 if result_type == "dice" else 0,
            "reward_key_hex": "10a58d9539bdc9b585b101",
            "quantity": 1,
        }

    def test_oldest_group_with_partial_dice_count_exports_without_warning(self):
        rows = [self._synthetic_row(1, "aa", "dice") for _ in range(5)]
        rows += [self._synthetic_row(2, "bb", "dice") for _ in range(5)]
        rows += [self._synthetic_row(3, "bb", "dice") for _ in range(4)]
        rows += [self._synthetic_row(3, "bb", "points_gift")]

        annotated = annotate_groups(rows)
        exported = [row for row in annotated if row["export_record"] is True]

        # Oldest group is a partially captured 10-pull on a full final page. Its
        # captured prefix is ordinal-stable, so it is exported with stable UIDs.
        self.assertEqual(len(exported), 15)
        oldest = [row for row in annotated if row["timestamp_raw_hex"] == "bb"]
        self.assertTrue(all(row["uid"] for row in oldest))
        self.assertTrue(all(row["uid_status"] == "stable" for row in oldest))
        self.assertEqual([row["timestamp_group_ordinal"] for row in oldest], list(range(10)))

    def test_incomplete_oldest_prefix_keeps_stable_uids(self):
        full = [self._synthetic_row(1, "aa", "dice") for _ in range(5)]
        full += [self._synthetic_row(2, "bb", "dice") for _ in range(3)]
        full += [self._synthetic_row(3, "bb", "dice") for _ in range(2)]
        truncated = [r for r in full if r["page"] in (1, 2)]

        full_rows = annotate_groups([dict(r) for r in full])
        trunc_rows = annotate_groups([dict(r) for r in truncated])

        full_uids = [r["uid"] for r in full_rows if r["timestamp_raw_hex"] == "bb"][:3]
        trunc_uids = [r["uid"] for r in trunc_rows if r["timestamp_raw_hex"] == "bb"]
        # Capturing only the first 3 of a 5-record oldest group yields the same
        # UIDs those rows have in the full capture.
        self.assertEqual(len(trunc_uids), 3)
        self.assertEqual(trunc_uids, full_uids)

    def test_oldest_group_with_ten_dice_exports_on_full_final_page(self):
        rows = [self._synthetic_row(1, "aa", "dice") for _ in range(5)]
        rows += [self._synthetic_row(2, "bb", "dice") for _ in range(5)]
        rows += [self._synthetic_row(3, "bb", "dice") for _ in range(5)]

        annotated = annotate_groups(rows)
        exported = [row for row in annotated if row["export_record"] is True]

        self.assertEqual(len(exported), 15)

    def test_run_selection_anchors_to_page_1_and_keeps_newest(self):
        # Page 2's response was lost: captured pages 1, 3, 4, 5.
        pairs = [(p, p * 2, 0, 0, 0, 0, b"", "permanent") for p in (1, 3, 4, 5)]
        run, warnings = select_continuous_run_from_page_1(pairs)

        # The page-1 run (just page 1, the newest history) is kept; later pages are
        # ignored with a gap warning, never silently discarding page 1.
        self.assertEqual([p[0] for p in run], [1])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["code"], "PAGE_GAP_DETECTED")
        self.assertEqual(warnings[0]["ignored_pages"], [3, 4, 5])

    def test_run_selection_warns_when_page_1_missing(self):
        pairs = [(p, p * 2, 0, 0, 0, 0, b"", "permanent") for p in (3, 4, 5)]
        run, warnings = select_continuous_run_from_page_1(pairs)

        self.assertEqual([p[0] for p in run], [3, 4, 5])
        self.assertEqual(warnings[0]["code"], "DID_NOT_START_AT_PAGE_1")

    def test_full_reference_scan_exports_all_rows(self):
        rows = load_reference_csv("monopoly_history_poc_10_all_44_pages_v4.csv")
        annotated = annotate_groups(rows)
        exported = [row for row in annotated if row["export_record"] is True]

        json_path = EXPORTS / "monopoly_history_export_10_all_44_pages_v4.json"
        if not json_path.exists():
            json_path = EXPORTS / "old" / "monopoly_history_export_10_all_44_pages_v4.json"
        if not json_path.exists():
            raise unittest.SkipTest(f"private reference fixture not present: {json_path}")
        with json_path.open(encoding="utf-8") as f:
            reference = json.load(f)

        self.assertEqual(len(annotated), reference["scan"]["decoded_records"])
        self.assertEqual(len(exported), reference["scan"]["exported_records"])

    def test_sanitized_export_omits_raw_packet_fields(self):
        rows = load_reference_csv("monopoly_history_poc_13_pages_1_to_5_v4.csv")
        annotated = annotate_groups(rows)
        export = build_export_json(annotated, [])

        self.assertEqual(export["format"], "nte-history-export")
        self.assertIn("exporter", export)
        self.assertNotIn("user_uid", export)
        self.assertNotIn("record_hex", export["records"][0])
        self.assertNotIn("request_msg", export["records"][0])
        self.assertNotIn("response_msg", export["records"][0])

    def test_export_includes_user_uid_when_provided(self):
        rows = load_reference_csv("monopoly_history_poc_13_pages_1_to_5_v4.csv")
        annotated = annotate_groups(rows)
        export = build_export_json(
            annotated,
            [],
            capture_source="npcap",
            user_uid="123456789",
        )

        self.assertEqual(list(export).index("user_uid"), list(export).index("records") - 1)
        self.assertEqual(export["capture_source"], "npcap")
        self.assertEqual(export["user_uid"], "123456789")

    def test_export_paths_include_user_uid_banner_and_timestamp(self):
        _csv_path, json_path = export_paths("limited_character", "218216016349")

        self.assertRegex(
            json_path.name,
            r"^218216016349_Limited_\d{8}_\d{6}(?:_\d+)?\.json$",
        )

    def test_extracts_user_uid_from_record_context(self):
        payload = (
            b"\x00" * 24
            + (218216016349).to_bytes(8, "little")
            + b"\x00\x00\x00\x00\x09\x00\x00\x00TagOthers\x00"
        )

        self.assertEqual(extract_user_uid(payload), "218216016349")

    def test_extracts_user_uid_from_private_spawn_record_context(self):
        payload = (
            b"\x88\x00\x00\x00\x10\x00\x00\x00"
            + (218216016349).to_bytes(8, "little")
            + b"\x08\x00\x0c\x00\x07\x00\x08\x00\x08\x00\x00\x00"
            + b"\x00\x00\x00\x01\x08\x00\x00\x00\x04\x00\x04\x00"
            + b"\x04\x00\x00\x00\x16\x00\x00\x00PrivateSpawnInfoRecord\x00"
        )

        self.assertEqual(extract_user_uid(payload), "218216016349")

    def test_does_not_extract_user_uid_from_wrong_record_offset(self):
        payload = (
            b"\x00" * 28
            + (218216016349).to_bytes(8, "little")
            + b"\x00\x00\x00\x00TagOthers\x00"
        )

        self.assertIsNone(extract_user_uid(payload))

    def test_does_not_extract_old_eight_digit_false_positive_as_user_uid(self):
        payload = (
            b"WholeVehicleData\x00\x00\x00\x00\x00o<\x00\x00\x05\x00\x00\x00"
            b"\x0b\x00\x00\x00Vehicle015\x00\x0b\x00\x00\x00buyvehicle\x00"
            b"\x09\x00\x00\x0015363624\x00\x06\x00\x00\x00"
        )

        self.assertIsNone(extract_user_uid(payload))

    def test_ipv4_parser_extracts_tcp_payload_for_user_uid_detection(self):
        payload = (
            (218216016349).to_bytes(8, "little")
            + b"\x00\x00\x00\x00\x09\x00\x00\x00TagOthers\x00"
        )
        tcp_header = bytearray(20)
        tcp_header[0:2] = (40000).to_bytes(2, "big")
        tcp_header[2:4] = (30000).to_bytes(2, "big")
        tcp_header[12] = 5 << 4
        total_len = 20 + len(tcp_header) + len(payload)
        ip_header = bytearray(20)
        ip_header[0] = 0x45
        ip_header[2:4] = total_len.to_bytes(2, "big")
        ip_header[9] = 6
        ip_header[12:16] = bytes([192, 0, 2, 1])
        ip_header[16:20] = bytes([198, 51, 100, 2])

        packet = parse_ipv4_packet(bytes(ip_header) + bytes(tcp_header) + payload)

        self.assertIsNotNone(packet)
        self.assertEqual(packet.protocol, "tcp")
        self.assertEqual(packet.payload, payload)

    def test_limited_selector_and_marker_decode(self):
        request = bytearray(45)
        request[31:35] = (4).to_bytes(4, "little")
        request[35:39] = (4220).to_bytes(4, "little")
        request[40:44] = (8).to_bytes(4, "little")
        self.assertEqual(history_request_kind(bytes(request)), "limited_character")

    def test_monopoly_request_allows_coalesced_trailing_payload(self):
        request = bytearray(45)
        request[31:35] = (25 * 4).to_bytes(4, "little")
        request[35:39] = (4220).to_bytes(4, "little")
        request[40:44] = (4).to_bytes(4, "little")
        coalesced = bytes(request) + bytes.fromhex(
            "007c669610062038461bc40100000872a34b93821a0219aa933b0a6b2ba34a6b"
        )

        self.assertEqual(history_request_kind(coalesced), "permanent")

    def test_arc_request_allows_coalesced_trailing_payload(self):
        request = bytearray(34)
        request[24:28] = (2060).to_bytes(4, "little")
        request[29:33] = (7 * 2).to_bytes(4, "little")

        self.assertTrue(is_arc_history_request(bytes(request) + bytes(32)))
        self.assertEqual(arc_request_page(bytes(request) + bytes(32)), 7)

        response = bytearray(220)
        response[0x50:0x54] = (4).to_bytes(4, "little")
        response[0x54:0x58] = (20).to_bytes(4, "little")
        response[0x58:0x5d] = bytes.fromhex("c4c0c4c000")
        marker_offset = 0x5d
        response[marker_offset:marker_offset + len(LIMITED_CHARACTER_MARKER)] = LIMITED_CHARACTER_MARKER
        timestamp_raw = (2556647947780680000).to_bytes(8, "little")
        response[marker_offset + len(LIMITED_CHARACTER_MARKER):marker_offset + len(LIMITED_CHARACTER_MARKER) + 8] = timestamp_raw

        rows = decode_response_records(bytes(response))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reward_id"], "1010")
        self.assertEqual(rows[0]["reward_name"], "Nanally")

    def test_v7_prefixed_points_gift_rows_override_visible_dice(self):
        cases = [
            ("limited_all_04_v7.csv", 41, "1020"),
            ("monopoly_history_poc_10_all_44_pages_v7.csv", 31, "1033"),
            ("monopoly_history_poc_10_all_44_pages_v7.csv", 86, "fork_PaperPlane"),
            ("monopoly_history_poc_10_all_44_pages_v7.csv", 141, "fork_Kite"),
            ("monopoly_history_poc_10_all_44_pages_v7.csv", 196, "1021"),
        ]
        for filename, row_index, reward_id in cases:
            with self.subTest(filename=filename, row_index=row_index):
                reference = load_v7_row(filename, row_index)
                decoded = decode_single_record(reference["record_hex"])
                self.assertEqual(decoded["result_type"], "points_gift")
                self.assertEqual(decoded["result_source_raw"], 0)
                self.assertEqual(decoded["dice"], 0)
                self.assertEqual(decoded["dice_raw_u32"], 0)
                self.assertEqual(decoded["reward_id"], reward_id)

    def test_v7_prefixed_chase_reward_overrides_visible_dice_and_quantity(self):
        reference = load_v7_row("limited_all_04_v7.csv", 61)
        decoded = decode_single_record(reference["record_hex"])
        decoded.update(
            {
                "pool_group_id": "Lottery_LimitedCharacter",
                "timestamp_group_ordinal": int(reference["timestamp_group_ordinal"]),
            }
        )

        self.assertEqual(decoded["result_type"], "chase_reward")
        self.assertEqual(decoded["result_source_raw"], -4)
        self.assertEqual(decoded["dice"], -4)
        self.assertEqual(decoded["dice_raw_u32"], -4)
        self.assertEqual(decoded["reward_id"], "Dice_ticket_01")
        self.assertEqual(decoded["quantity"], 30)
        self.assertEqual(make_uid(decoded, int(reference["timestamp_group_ordinal"])), "7d035ec098f856f81b403ea538810145")

    def test_batched_monopoly_response_normalizes_embedded_page_header(self):
        page_7 = [load_v7_row("limited_all_04_v7.csv", row) for row in range(31, 36)]
        page_8 = [load_v7_row("limited_all_04_v7.csv", row) for row in range(36, 41)]
        embedded_header = bytes.fromhex(
            "100126675671c6e0ecfcb769070000000c08000000100000003e0800000004000000"
            "486c0000001835bdb9bdc1bdb1e531bdd1d195c9e549958dbdc9911185d18501"
        )
        response = (
            bytes(0x50)
            + b"".join(bytes.fromhex(row["record_hex"]) for row in page_7)
            + embedded_header
            + b"".join(bytes.fromhex(row["record_hex"]) for row in page_8)
        )

        decoded = decode_response_records(response)

        self.assertEqual(len(decoded), 10)
        self.assertEqual(decoded[5]["reward_id"], page_8[0]["reward_id"])
        self.assertEqual(decoded[5]["dice"], 5)
        self.assertEqual(decoded[5]["result_type"], "dice")
        self.assertEqual(decoded[5]["record_hex"], page_8[0]["record_hex"])

    def test_monopoly_response_parser_realigns_bit_packed_payload(self):
        reference_rows = [
            load_v7_row("limited_all_04_v7.csv", row)
            for row in range(51, 61)
        ]
        response = bytes(0x50) + b"".join(
            bytes.fromhex(row["record_hex"]) for row in reference_rows
        )
        packed = bytearray()
        carry = 0b10101
        for byte in response:
            packed.append(carry | ((byte << 5) & 0xFF))
            carry = byte >> 3
        packed.append(carry)

        decoded = decode_response_records(bytes(packed))

        self.assertEqual(len(decoded), 10)
        self.assertEqual(
            [row["record_hex"] for row in decoded],
            [row["record_hex"] for row in reference_rows],
        )

    def test_page_gap_warning_reports_ignored_pages(self):
        pairs = [(p, p * 2, 0, 0, 0, 0, b"", "permanent") for p in (1, 2, 3, 5)]
        run, warnings = select_continuous_run_from_page_1(pairs)
        self.assertEqual([p[0] for p in run], [1, 2, 3])
        self.assertEqual(warnings[0]["code"], "PAGE_GAP_DETECTED")
        self.assertEqual(warnings[0]["ignored_pages"], [5])

    def test_arc_key_timestamp_and_uid_match_reference(self):
        row = load_arc_csv("arc_pull_10_all_pages_v2.csv")[0]
        self.assertEqual(decode_arc_key(bytes.fromhex(row["arc_key_hex"])), "fork_nonos")
        _ticks, _unix, decoded = decode_arc_timestamp(bytes.fromhex(row["timestamp_raw_hex"]))
        self.assertEqual(decoded, "2026-06-10 23:46:29")
        self.assertEqual(
            make_arc_uid(row["timestamp_raw_hex"], int(row["timestamp_group_ordinal"]), row["arc_key_hex"]),
            row["uid"],
        )

    def test_arc_response_parser_matches_reference_first_page(self):
        reference_rows = load_arc_csv("arc_pull_10_all_pages_v2.csv")[:5]
        response = bytes(0x4C) + b"".join(bytes.fromhex(row["record_hex"]) for row in reference_rows)
        decoded = parse_arc_response(response)
        self.assertEqual(len(decoded), 5)
        self.assertEqual([row["reward_id"] for row in decoded[:3]], ["fork_nonos", "fork_nonos", "fork_Prokaryon"])
        self.assertEqual(decoded[0]["reward_type"], "arc")
        self.assertEqual(decoded[0]["reward_key_hex"], reference_rows[0]["arc_key_hex"])

    def test_arc_response_parser_rejects_invalid_timestamp_noise(self):
        response = bytearray(0x4C)
        response += (10).to_bytes(4, "little")
        response += bytes.fromhex("ccdee4d6be")
        response += (8).to_bytes(4, "little")
        response += b"garb"
        response += (0xFFFFFFFFFFFFFFFF).to_bytes(8, "little")

        self.assertEqual(parse_arc_response(bytes(response)), [])

    def test_arc_partial_timestamp_group_is_exported_without_warning(self):
        rows = load_arc_csv("arc_pages_1_to_5_v2.csv")
        pairs = []
        for page in range(1, 6):
            page_rows = [row for row in rows if int(row["page"]) == page]
            response = bytes(0x4C) + b"".join(bytes.fromhex(row["record_hex"]) for row in page_rows)
            pairs.append((page, page * 2, page, 1.0, page + 100, 1.1, response))
        decoded = build_arc_rows_from_pairs(pairs)
        exported = [row for row in decoded if row["export_record"] is True]

        # The oldest group is a 10-pull split by stopping at page 5 (5 of 10 rows).
        # Its captured prefix is ordinal-stable, so every row is exported with a
        # stable UID and no warning.
        self.assertEqual(len(decoded), 25)
        self.assertEqual(len(exported), 25)
        self.assertTrue(all(row["uid"] for row in decoded))
        self.assertTrue(all(row["uid_status"] == "stable" for row in decoded))

    def test_arc_incomplete_prefix_keeps_stable_uids(self):
        rows = load_arc_csv("arc_pull_10_all_pages_v2.csv")
        # Build a full 2-page (10-record) group, then a truncated 1-page version.
        full_pairs, trunc_pairs = [], []
        for page in (1, 2):
            page_rows = [r for r in rows if int(r["page"]) == page]
            response = bytes(0x4C) + b"".join(bytes.fromhex(r["record_hex"]) for r in page_rows)
            full_pairs.append((page, page * 2, page, 1.0, page + 100, 1.1, response))
            if page == 1:
                trunc_pairs.append((page, page * 2, page, 1.0, page + 100, 1.1, response))

        ts = rows[0]["timestamp_raw_hex"]
        full = [r for r in build_arc_rows_from_pairs(full_pairs) if r["timestamp_raw_hex"] == ts]
        trunc = [r for r in build_arc_rows_from_pairs(trunc_pairs) if r["timestamp_raw_hex"] == ts]
        self.assertTrue(trunc)
        self.assertEqual([r["uid"] for r in trunc], [r["uid"] for r in full[: len(trunc)]])

    def test_arc_row_builder_accepts_live_pairs_with_kind(self):
        reference_rows = load_arc_csv("arc_pull_10_all_pages_v2.csv")[:5]
        response = bytes(0x4C) + b"".join(bytes.fromhex(row["record_hex"]) for row in reference_rows)
        decoded = build_arc_rows_from_pairs([(1, 2, 1, 1.0, 2, 1.1, response, "arc_miracle_box")])
        self.assertEqual(len(decoded), 5)
        self.assertEqual(decoded[0]["reward_id"], "fork_nonos")

    def test_arc_export_is_shared_pity(self):
        reference_rows = load_arc_csv("arc_pull_10_all_pages_v2.csv")[:10]
        response = bytes(0x4C) + b"".join(bytes.fromhex(row["record_hex"]) for row in reference_rows)
        rows = build_arc_rows_from_pairs([(1, 2, 1, 1.0, 2, 1.1, response, "arc_miracle_box")])
        export = build_export_json(rows, [])
        self.assertEqual(export["banner"]["id"], "Arc_MiracleBox")
        self.assertIs(export["banner"]["shared_pity"], True)

    def test_group_detection_counts_only_dice_records_but_uid_ordinals_keep_all_rows(self):
        rows = [
            {
                "page": 1,
                "timestamp_raw_hex": "aa",
                "timestamp_decoded": "2026-01-01 00:00:00",
                "result_type": "dice",
                "dice": 1,
                "reward_key_hex": "k1",
                "quantity": 1,
            },
            {
                "page": 1,
                "timestamp_raw_hex": "aa",
                "timestamp_decoded": "2026-01-01 00:00:00",
                "result_type": "points_gift",
                "dice": 0,
                "reward_key_hex": "k2",
                "quantity": 1,
            },
            {
                "page": 1,
                "timestamp_raw_hex": "aa",
                "timestamp_decoded": "2026-01-01 00:00:00",
                "result_type": "chase_reward",
                "dice": -4,
                "reward_key_hex": "k3",
                "quantity": 30,
            },
            {
                "page": 1,
                "timestamp_raw_hex": "aa",
                "timestamp_decoded": "2026-01-01 00:00:00",
                "result_type": "dice",
                "dice": 2,
                "reward_key_hex": "k4",
                "quantity": 1,
            },
            {
                "page": 1,
                "timestamp_raw_hex": "bb",
                "timestamp_decoded": "2026-01-01 00:01:00",
                "result_type": "dice",
                "dice": 3,
                "reward_key_hex": "k5",
                "quantity": 1,
            },
        ]

        annotated = annotate_groups(rows)

        # Ordinals cover every row in the group, but the dice-only count drives
        # timestamp_group_size_seen (2 dice in the 4-record group).
        self.assertEqual([row["timestamp_group_ordinal"] for row in annotated[:4]], [0, 1, 2, 3])
        self.assertEqual({row["timestamp_group_size_seen"] for row in annotated[:4]}, {2})
        self.assertEqual({row["timestamp_group_record_size_seen"] for row in annotated[:4]}, {4})
        self.assertTrue(all(row["export_record"] for row in annotated))

    def test_live_session_pairs_request_and_response(self):
        session = LiveHistorySession("192.168.0.10")

        request = bytearray(45)
        request[31:35] = (4).to_bytes(4, "little")
        request[35:39] = (4220).to_bytes(4, "little")
        request[40:44] = (4).to_bytes(4, "little")

        response = bytearray(220)
        response[0x50:0x50 + len(MARKER)] = MARKER
        response[0x50 + len(MARKER):0x50 + len(MARKER) + 8] = (
            2556647947780680000
        ).to_bytes(8, "little")

        self.assertFalse(
            session.process_packet(
                UdpPacket(
                    timestamp=1.0,
                    src_ip="192.168.0.10",
                    dst_ip="203.0.113.5",
                    src_port=50000,
                    dst_port=40000,
                    payload=bytes(request),
                )
            )
        )
        self.assertTrue(
            session.process_packet(
                UdpPacket(
                    timestamp=1.2,
                    src_ip="203.0.113.5",
                    dst_ip="192.168.0.10",
                    src_port=40000,
                    dst_port=50000,
                    payload=bytes(response),
                )
            )
        )
        self.assertEqual(len(session.pairs), 1)
        self.assertEqual(session.last_page_seen, 1)

    def test_live_session_pairs_pipelined_and_batched_pages(self):
        session = LiveHistorySession("192.168.0.10")

        def request_packet(page, timestamp):
            request = bytearray(45)
            request[31:35] = (page * 4).to_bytes(4, "little")
            request[35:39] = (4220).to_bytes(4, "little")
            request[40:44] = (4).to_bytes(4, "little")
            return UdpPacket(
                timestamp=timestamp,
                src_ip="192.168.0.10",
                dst_ip="203.0.113.5",
                src_port=50000,
                dst_port=40000,
                payload=bytes(request),
            )

        timestamp = (2556647947780680000).to_bytes(8, "little")

        def response_packet(record_count, packet_timestamp):
            response = bytearray(0x50)
            for _ in range(record_count):
                response += bytes(4) + MARKER + timestamp
            return UdpPacket(
                timestamp=packet_timestamp,
                src_ip="203.0.113.5",
                dst_ip="192.168.0.10",
                src_port=40000,
                dst_port=50000,
                payload=bytes(response),
            )

        for page in range(1, 9):
            session.process_packet(request_packet(page, 1.0 + page / 10))

        self.assertTrue(session.process_packet(response_packet(10, 2.0)))
        self.assertEqual([pair[0] for pair in session.pairs], [1, 2])
        self.assertEqual([pair[8:10] for pair in session.pairs], [(0, 5), (5, 5)])

        self.assertTrue(session.process_packet(response_packet(10, 2.1)))
        self.assertEqual([pair[0] for pair in session.pairs], [1, 2, 3, 4])
        self.assertEqual(session.missing_pages("permanent"), [])
        rows = session.build_rows("permanent")
        self.assertEqual(len(rows), 20)
        self.assertEqual(
            {page: sum(row["page"] == page for row in rows) for page in range(1, 5)},
            {1: 5, 2: 5, 3: 5, 4: 5},
        )

        session.process_packet(request_packet(9, 2.2))
        self.assertTrue(session.process_packet(response_packet(4, 2.3)))
        self.assertEqual(session.pairs[-1][0], 9)
        self.assertEqual(session.pairs[-1][8:10], (0, 4))

    def test_live_session_new_page_one_starts_clean_recovery_cycle(self):
        session = LiveHistorySession("192.168.0.10")

        def request_packet(page, timestamp):
            request = bytearray(45)
            request[31:35] = (page * 4).to_bytes(4, "little")
            request[35:39] = (4220).to_bytes(4, "little")
            request[40:44] = (4).to_bytes(4, "little")
            return UdpPacket(
                timestamp=timestamp,
                src_ip="192.168.0.10",
                dst_ip="203.0.113.5",
                src_port=50000,
                dst_port=40000,
                payload=bytes(request),
            )

        session.process_packet(request_packet(7, 1.0))
        session.process_packet(request_packet(8, 1.1))
        session.process_packet(request_packet(1, 2.0))

        self.assertEqual([request.page for request in session.pending], [1])
        self.assertEqual(
            session.missing_page_reason("permanent", 7),
            "request captured; no matching response page was captured",
        )

        timestamp = (2556647947780680000).to_bytes(8, "little")
        response = bytearray(0x50)
        for _ in range(5):
            response += bytes(4) + MARKER + timestamp
        self.assertTrue(
            session.process_packet(
                UdpPacket(
                    timestamp=2.1,
                    src_ip="203.0.113.5",
                    dst_ip="192.168.0.10",
                    src_port=40000,
                    dst_port=50000,
                    payload=bytes(response),
                )
            )
        )
        self.assertEqual(session.pairs[-1][0], 1)
        self.assertEqual(session.missing_pages("permanent"), [])

    def test_live_session_reports_unrecognized_response_candidate(self):
        session = LiveHistorySession("192.168.0.10")

        def request_packet(page, timestamp):
            request = bytearray(45)
            request[31:35] = (page * 4).to_bytes(4, "little")
            request[35:39] = (4220).to_bytes(4, "little")
            request[40:44] = (4).to_bytes(4, "little")
            return UdpPacket(
                timestamp=timestamp,
                src_ip="192.168.0.10",
                dst_ip="203.0.113.5",
                src_port=50000,
                dst_port=40000,
                payload=bytes(request),
            )

        session.process_packet(request_packet(1, 1.0))
        session.process_packet(
            UdpPacket(
                timestamp=1.1,
                src_ip="203.0.113.5",
                dst_ip="192.168.0.10",
                src_port=40000,
                dst_port=50000,
                payload=bytes(220),
            )
        )
        session.process_packet(request_packet(2, 1.2))

        self.assertEqual(
            session.missing_page_reason("permanent", 1),
            "1 matching inbound UDP packet(s) captured but not recognized as history response (lengths: 220)",
        )

    def test_live_session_ignores_non_history_udp_packets(self):
        session = LiveHistorySession("192.168.0.10")

        request = bytearray(45)
        request[31:35] = (4).to_bytes(4, "little")
        request[35:39] = (4220).to_bytes(4, "little")
        request[40:44] = (4).to_bytes(4, "little")

        noise = b"not-a-history-response" * 20

        session.process_packet(
            UdpPacket(
                timestamp=1.0,
                src_ip="192.168.0.10",
                dst_ip="203.0.113.5",
                src_port=50000,
                dst_port=40000,
                payload=bytes(request),
            )
        )
        self.assertFalse(
            session.process_packet(
                UdpPacket(
                    timestamp=1.1,
                    src_ip="203.0.113.5",
                    dst_ip="192.168.0.10",
                    src_port=40000,
                    dst_port=50000,
                    payload=noise,
                )
            )
        )
        self.assertEqual(len(session.pairs), 0)


if __name__ == "__main__":
    unittest.main()
