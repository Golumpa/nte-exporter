from tests.support import *  # noqa: F401,F403
from nte_history_exporter import __version__


class ExportContractTests(unittest.TestCase):
    def test_sanitized_export_omits_raw_packet_fields(self):
        annotated = annotate_groups(fixture_session().build_rows("permanent"))
        export = build_export_json(annotated, [])

        self.assertEqual(export["format"], "nte-history-export")
        self.assertIn("exporter", export)
        self.assertNotIn("user_uid", export)
        self.assertNotIn("record_hex", export["records"][0])
        self.assertNotIn("request_msg", export["records"][0])
        self.assertNotIn("response_msg", export["records"][0])

    def test_export_includes_user_uid_when_provided(self):
        annotated = annotate_groups(fixture_session().build_rows("permanent"))
        export = build_export_json(
            annotated,
            [],
            capture_source="npcap",
            user_uid="123456789",
        )

        self.assertEqual(list(export).index("user_uid"), list(export).index("records") - 1)
        self.assertEqual(export["capture_source"], "npcap")
        self.assertEqual(export["user_uid"], "123456789")

    def test_debug_csv_includes_exporter_version(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "debug.csv"
            write_csv(path, [{"uid": "abc123"}])

            with path.open(newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual(rows[0]["exporter_version"], __version__)
        self.assertEqual(rows[0]["uid"], "abc123")

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
