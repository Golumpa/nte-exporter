import csv
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURES = ROOT / "tests" / "fixtures"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nte_history_exporter import __version__
from nte_history_exporter.decoder.boundary import annotate_groups, make_uid
from nte_history_exporter.constants import LIMITED_CHARACTER_MARKER, MARKER
from nte_history_exporter.decoder.boundary import select_continuous_run_from_page_1
from nte_history_exporter.decoder.protocol import decode_response_records, history_request_kind
from nte_history_exporter.constants import POOL_META
from nte_history_exporter.mappings import ARC_META, CHARACTERS, ITEMS, REWARDS_BY_ID
from nte_history_exporter.decoder.protocol import decode_reward_key, infer_reward_type
from nte_history_exporter.decoder.user_uid import extract_user_uid
from nte_history_exporter.export.csv_export import write_csv
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
from nte_history_exporter.update_check import UpdateInfo, check_for_update, is_newer_version


def decode_single_record(record_hex):
    return decode_response_records(bytes(0x50) + bytes.fromhex(record_hex))[0]


def load_network_fixture():
    path = FIXTURES / "synthetic_history_network.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_capture_diagnostics_fixture():
    path = FIXTURES / "synthetic_capture_diagnostics.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def diagnostic_fixture_session():
    fixture = load_capture_diagnostics_fixture()
    session = LiveHistorySession(fixture["local_ip"])
    for packet in fixture["packets"]:
        if "payload_hex" in packet:
            payload = bytes.fromhex(packet["payload_hex"])
        else:
            payload = bytes.fromhex(packet["payload_byte"]) * packet["payload_length"]
        session.process_packet(
            UdpPacket(
                timestamp=packet["timestamp"],
                src_ip=packet["src_ip"],
                dst_ip=packet["dst_ip"],
                src_port=packet["src_port"],
                dst_port=packet["dst_port"],
                payload=payload,
                protocol=packet["protocol"],
            )
        )
    return session


def fixture_packets(scenario=None):
    fixture = load_network_fixture()
    packets = fixture["packets"]
    if scenario is not None:
        packets = [packet for packet in packets if packet["scenario"] == scenario]
    return [
        UdpPacket(
            timestamp=packet["timestamp"],
            src_ip=packet["src_ip"],
            dst_ip=packet["dst_ip"],
            src_port=packet["src_port"],
            dst_port=packet["dst_port"],
            payload=bytes.fromhex(packet["payload_hex"]),
            protocol=packet["protocol"],
        )
        for packet in packets
    ]


def fixture_payload(label):
    fixture = load_network_fixture()
    packet = next(packet for packet in fixture["packets"] if packet["label"] == label)
    return bytes.fromhex(packet["payload_hex"])


def fixture_session():
    fixture = load_network_fixture()
    session = LiveHistorySession(fixture["local_ip"])
    for packet in fixture_packets("replay"):
        session.process_packet(packet)
    return session
