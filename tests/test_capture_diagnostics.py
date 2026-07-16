from tests.support import *  # noqa: F401,F403

from nte_history_exporter.live_capture.diagnostics import (
    new_diagnostics_path,
    write_capture_diagnostics,
)


class CaptureDiagnosticsTests(unittest.TestCase):
    def test_successful_network_replay_reports_capture_pipeline_counts(self):
        report = fixture_session().diagnostic_report()

        self.assertEqual(
            report["counters"],
            {
                "history_requests_recognized": 10,
                "history_responses_decoded": 10,
                "packets_seen": 20,
                "pages_matched": 10,
                "udp_packets_seen": 20,
            },
        )
        self.assertEqual(report["reason_counts"], {})
        self.assertEqual(report["pending_requests"], [])

    def test_synthetic_replay_reports_actionable_rejection_reasons(self):
        fixture = load_capture_diagnostics_fixture()
        report = diagnostic_fixture_session().diagnostic_report()
        expected = fixture["expected"]

        self.assertEqual(report["format"], "nte-capture-diagnostics")
        self.assertEqual(report["format_version"], 1)
        self.assertEqual(report["counters"]["packets_seen"], expected["packets_seen"])
        self.assertEqual(
            report["counters"]["history_requests_recognized"],
            expected["history_requests_recognized"],
        )
        self.assertEqual(
            report["counters"]["response_candidates_rejected"],
            expected["response_candidates_rejected"],
        )
        self.assertEqual(report["event_counts"], expected["event_counts"])
        self.assertEqual(report["reason_counts"], expected["reason_counts"])
        self.assertEqual(report["pending_requests"][0]["response_candidates"], 2)
        self.assertEqual(
            report["pending_requests"][0]["response_candidate_lengths"],
            expected["pending_candidate_lengths"],
        )

    def test_diagnostic_fixture_contains_only_synthetic_network_identity(self):
        fixture = load_capture_diagnostics_fixture()
        self.assertTrue(fixture["privacy"]["synthetic"])
        self.assertFalse(fixture["privacy"]["contains_user_uid"])
        self.assertFalse(fixture["privacy"]["contains_raw_account_session"])

        allowed_ips = {"192.0.2.10", "198.51.100.20"}
        for packet in fixture["packets"]:
            with self.subTest(label=packet["label"]):
                self.assertIn(packet["src_ip"], allowed_ips)
                self.assertIn(packet["dst_ip"], allowed_ips)
                if "payload_hex" in packet:
                    payload = bytes.fromhex(packet["payload_hex"])
                else:
                    payload = bytes.fromhex(packet["payload_byte"]) * packet["payload_length"]
                self.assertIsNone(extract_user_uid(payload))

    def test_diagnostic_report_excludes_capture_identity_and_payload_data(self):
        report = diagnostic_fixture_session().diagnostic_report()
        serialized = json.dumps(report)
        forbidden_keys = {
            "src_ip",
            "dst_ip",
            "src_port",
            "dst_port",
            "timestamp",
            "payload",
            "payload_hex",
            "user_uid",
        }

        def assert_safe(value):
            if isinstance(value, dict):
                self.assertTrue(forbidden_keys.isdisjoint(value))
                for child in value.values():
                    assert_safe(child)
            elif isinstance(value, list):
                for child in value:
                    assert_safe(child)

        assert_safe(report)
        self.assertNotIn("192.0.2.10", serialized)
        self.assertNotIn("198.51.100.20", serialized)
        self.assertNotIn("1893456000", serialized)

    def test_diagnostics_are_debug_sidecar_not_public_export_data(self):
        session = diagnostic_fixture_session()
        export = build_export_json([], [])
        self.assertNotIn("diagnostics", export)
        self.assertNotIn("capture_diagnostics", export)

        with TemporaryDirectory() as temp_dir:
            diagnostics_path = new_diagnostics_path(temp_dir)
            write_capture_diagnostics(diagnostics_path, session.diagnostic_report())
            written = json.loads(diagnostics_path.read_text(encoding="utf-8"))

        self.assertEqual(written, session.diagnostic_report())
        self.assertRegex(diagnostics_path.name, r"^Capture_\d{8}_\d{6}\.diagnostics\.json$")
        self.assertNotIn("user", diagnostics_path.name.casefold())
