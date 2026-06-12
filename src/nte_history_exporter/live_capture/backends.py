from __future__ import annotations

import socket
import sys
from dataclasses import dataclass
from typing import Iterator, Protocol

from nte_history_exporter.live_capture.libpcap import (
    CaptureStats,
    LibpcapUnavailable,
    open_libpcap_capture,
)
from nte_history_exporter.live_capture.windows_raw import (
    ParsedIpUdpPacket,
    open_raw_udp_socket,
    read_packets,
)


class CaptureBackend(Protocol):
    name: str
    detail: str
    fallback_reason: str

    def packets(self) -> Iterator[ParsedIpUdpPacket | None]: ...

    def stats(self) -> CaptureStats | None: ...

    def close(self) -> None: ...


@dataclass
class RawSocketCapture:
    local_ip: str
    fallback_reason: str = ""

    def __post_init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("the raw socket capture backend is only available on Windows")
        self.name = "windows_raw"
        self.detail = self.local_ip
        self.socket = open_raw_udp_socket(self.local_ip)

    def packets(self) -> Iterator[ParsedIpUdpPacket | None]:
        return read_packets(self.socket)

    def stats(self) -> CaptureStats | None:
        return None

    def close(self) -> None:
        try:
            self.socket.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
        except Exception:
            pass
        self.socket.close()


def open_capture_backend(local_ip: str, requested: str = "auto") -> CaptureBackend:
    if requested not in {"auto", "libpcap", "raw"}:
        raise ValueError(f"unknown capture backend: {requested}")

    if requested in {"auto", "libpcap"}:
        try:
            capture = open_libpcap_capture(local_ip)
        except LibpcapUnavailable as exc:
            if requested != "auto" or sys.platform != "win32":
                raise
            return RawSocketCapture(local_ip, fallback_reason=str(exc))
        capture.name = "npcap" if sys.platform == "win32" else "libpcap"
        capture.detail = capture.device
        capture.fallback_reason = ""
        return capture

    return RawSocketCapture(local_ip)
