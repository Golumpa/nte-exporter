from tests.support import *  # noqa: F401,F403
from nte_history_exporter.live_capture.libpcap import _extract_ipv4_frame, _load_library


class CaptureBackendTests(unittest.TestCase):
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
