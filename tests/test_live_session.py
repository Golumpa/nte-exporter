from tests.support import *  # noqa: F401,F403


class LiveSessionTests(unittest.TestCase):
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

