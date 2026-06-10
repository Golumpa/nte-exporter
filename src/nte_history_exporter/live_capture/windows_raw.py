from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

from nte_history_exporter.live_capture.session import UdpPacket


@dataclass
class ParsedIpUdpPacket:
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    payload: bytes


def detect_local_ipv4() -> str:
    candidates: list[str] = []
    try:
        host = socket.gethostname()
        for ip in socket.gethostbyname_ex(host)[2]:
            if not ip.startswith("127."):
                candidates.append(ip)
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("1.1.1.1", 80))
            ip = probe.getsockname()[0]
            if not ip.startswith("127."):
                candidates.insert(0, ip)
    except OSError:
        pass

    if not candidates:
        raise RuntimeError("could not determine a usable local IPv4 address")
    return candidates[0]


def parse_ipv4_udp_packet(data: bytes) -> ParsedIpUdpPacket | None:
    if len(data) < 28:
        return None
    version_ihl = data[0]
    if version_ihl >> 4 != 4:
        return None
    ihl = (version_ihl & 0x0F) * 4
    if len(data) < ihl + 8:
        return None
    protocol = data[9]
    if protocol != 17:
        return None

    src_ip = socket.inet_ntoa(data[12:16])
    dst_ip = socket.inet_ntoa(data[16:20])
    src_port, dst_port, udp_len, _checksum = struct.unpack_from("!HHHH", data, ihl)
    payload = data[ihl + 8 : ihl + udp_len]
    return ParsedIpUdpPacket(src_ip, dst_ip, src_port, dst_port, payload)


def open_raw_udp_socket(local_ip: str) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
    sock.bind((local_ip, 0))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
    sock.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
    sock.settimeout(0.5)
    return sock


def read_packets(sock: socket.socket):
    while True:
        try:
            data, _addr = sock.recvfrom(65535)
        except socket.timeout:
            yield None
            continue
        packet = parse_ipv4_udp_packet(data)
        if packet is None:
            continue
        yield packet
