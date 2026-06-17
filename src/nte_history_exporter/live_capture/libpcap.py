from __future__ import annotations

import ctypes
import ctypes.util
import os
import socket
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from nte_history_exporter.live_capture.windows_raw import ParsedIpUdpPacket, parse_ipv4_packet

PCAP_ERRBUF_SIZE = 256
SNAP_LENGTH = 65535
CAPTURE_BUFFER_SIZE = 16 * 1024 * 1024
READ_TIMEOUT_MS = 100

DLT_NULL = 0
DLT_EN10MB = 1
DLT_RAW_BSD = 12
DLT_RAW = 101
DLT_LOOP = 108
DLT_LINUX_SLL = 113
DLT_LINUX_SLL2 = 276


class LibpcapUnavailable(RuntimeError):
    pass


class _SockAddr(ctypes.Structure):
    _fields_ = [("sa_family", ctypes.c_ushort), ("sa_data", ctypes.c_ubyte * 14)]


class _PcapAddr(ctypes.Structure):
    pass


_PcapAddrPtr = ctypes.POINTER(_PcapAddr)
_PcapAddr._fields_ = [
    ("next", _PcapAddrPtr),
    ("addr", ctypes.POINTER(_SockAddr)),
    ("netmask", ctypes.POINTER(_SockAddr)),
    ("broadaddr", ctypes.POINTER(_SockAddr)),
    ("dstaddr", ctypes.POINTER(_SockAddr)),
]


class _PcapIf(ctypes.Structure):
    pass


_PcapIfPtr = ctypes.POINTER(_PcapIf)
_PcapIf._fields_ = [
    ("next", _PcapIfPtr),
    ("name", ctypes.c_char_p),
    ("description", ctypes.c_char_p),
    ("addresses", _PcapAddrPtr),
    ("flags", ctypes.c_uint),
]


class _Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


class _PcapPacketHeader(ctypes.Structure):
    _fields_ = [("ts", _Timeval), ("caplen", ctypes.c_uint), ("length", ctypes.c_uint)]


class _BpfProgram(ctypes.Structure):
    _fields_ = [("bf_len", ctypes.c_uint), ("bf_insns", ctypes.c_void_p)]


class _PcapStat(ctypes.Structure):
    # Npcap adds ps_capt after the three standard libpcap counters. Keeping the
    # extra field is harmless on platforms that only populate the first three.
    _fields_ = [
        ("ps_recv", ctypes.c_uint),
        ("ps_drop", ctypes.c_uint),
        ("ps_ifdrop", ctypes.c_uint),
        ("ps_capt", ctypes.c_uint),
    ]


@dataclass
class CaptureStats:
    received: int
    dropped: int
    interface_dropped: int


def _windows_npcap_directory() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "Npcap"


def _load_library() -> ctypes.CDLL:
    candidates: list[str] = []
    dll_directory = None
    if sys.platform == "win32":
        npcap_dir = _windows_npcap_directory()
        if npcap_dir.is_dir() and hasattr(os, "add_dll_directory"):
            dll_directory = os.add_dll_directory(str(npcap_dir))
        candidates.append(str(npcap_dir / "wpcap.dll"))
        candidates.append("wpcap.dll")
    elif sys.platform == "darwin":
        candidates.extend(
            [
                ctypes.util.find_library("pcap") or "",
                "/usr/lib/libpcap.A.dylib",
                "/usr/lib/libpcap.dylib",
            ]
        )
    else:
        candidates.extend([ctypes.util.find_library("pcap") or "", "libpcap.so.1", "libpcap.so"])

    errors = []
    try:
        for candidate in candidates:
            if not candidate:
                continue
            try:
                return ctypes.CDLL(candidate)
            except OSError as exc:
                errors.append(str(exc))
    finally:
        if dll_directory is not None:
            dll_directory.close()

    detail = f": {errors[-1]}" if errors else ""
    if sys.platform == "win32":
        raise LibpcapUnavailable(f"Npcap is not installed or could not be loaded{detail}")
    raise LibpcapUnavailable(f"libpcap is not installed or could not be loaded{detail}")


def _configure_api(lib: ctypes.CDLL) -> None:
    lib.pcap_findalldevs.argtypes = [ctypes.POINTER(_PcapIfPtr), ctypes.c_char_p]
    lib.pcap_findalldevs.restype = ctypes.c_int
    lib.pcap_freealldevs.argtypes = [_PcapIfPtr]

    lib.pcap_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    lib.pcap_create.restype = ctypes.c_void_p
    lib.pcap_set_snaplen.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.pcap_set_promisc.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.pcap_set_timeout.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.pcap_set_buffer_size.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.pcap_activate.argtypes = [ctypes.c_void_p]
    lib.pcap_activate.restype = ctypes.c_int
    lib.pcap_close.argtypes = [ctypes.c_void_p]
    lib.pcap_geterr.argtypes = [ctypes.c_void_p]
    lib.pcap_geterr.restype = ctypes.c_char_p
    lib.pcap_datalink.argtypes = [ctypes.c_void_p]
    lib.pcap_datalink.restype = ctypes.c_int

    lib.pcap_compile.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_BpfProgram),
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    lib.pcap_setfilter.argtypes = [ctypes.c_void_p, ctypes.POINTER(_BpfProgram)]
    lib.pcap_freecode.argtypes = [ctypes.POINTER(_BpfProgram)]

    lib.pcap_next_ex.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(_PcapPacketHeader)),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
    ]
    lib.pcap_next_ex.restype = ctypes.c_int
    lib.pcap_stats.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PcapStat)]
    lib.pcap_stats.restype = ctypes.c_int

def _pcap_error(lib: ctypes.CDLL, handle: ctypes.c_void_p) -> str:
    raw = lib.pcap_geterr(handle)
    return raw.decode("utf-8", errors="replace") if raw else "unknown libpcap error"


def _ipv4_from_sockaddr(address: ctypes.POINTER(_SockAddr)) -> str | None:
    if not address:
        return None
    raw = ctypes.string_at(address, 16)
    family = raw[1] if sys.platform == "darwin" else struct.unpack_from("=H", raw, 0)[0]
    return socket.inet_ntoa(raw[4:8]) if family == socket.AF_INET else None


def _find_windows_device(local_ip: str) -> str | None:
    if sys.platform != "win32":
        return None

    from ctypes import wintypes

    class IpAddressString(ctypes.Structure):
        _fields_ = [("value", ctypes.c_char * 16)]

    class IpMaskString(ctypes.Structure):
        _fields_ = [("value", ctypes.c_char * 16)]

    class IpAddrString(ctypes.Structure):
        pass

    IpAddrStringPtr = ctypes.POINTER(IpAddrString)
    IpAddrString._fields_ = [
        ("next", IpAddrStringPtr),
        ("ip_address", IpAddressString),
        ("ip_mask", IpMaskString),
        ("context", wintypes.DWORD),
    ]

    class IpAdapterInfo(ctypes.Structure):
        pass

    IpAdapterInfoPtr = ctypes.POINTER(IpAdapterInfo)
    IpAdapterInfo._fields_ = [
        ("next", IpAdapterInfoPtr),
        ("combo_index", wintypes.DWORD),
        ("adapter_name", ctypes.c_char * 260),
        ("description", ctypes.c_char * 132),
        ("address_length", wintypes.UINT),
        ("address", ctypes.c_ubyte * 8),
        ("index", wintypes.DWORD),
        ("adapter_type", wintypes.UINT),
        ("dhcp_enabled", wintypes.UINT),
        ("current_ip_address", IpAddrStringPtr),
        ("ip_address_list", IpAddrString),
        ("gateway_list", IpAddrString),
        ("dhcp_server", IpAddrString),
        ("have_wins", wintypes.BOOL),
        ("primary_wins_server", IpAddrString),
        ("secondary_wins_server", IpAddrString),
        ("lease_obtained", ctypes.c_longlong),
        ("lease_expires", ctypes.c_longlong),
    ]

    ip_helper = ctypes.WinDLL("iphlpapi")
    ip_helper.GetAdaptersInfo.argtypes = [IpAdapterInfoPtr, ctypes.POINTER(wintypes.ULONG)]
    ip_helper.GetAdaptersInfo.restype = wintypes.DWORD

    size = wintypes.ULONG(0)
    if ip_helper.GetAdaptersInfo(None, ctypes.byref(size)) not in (0, 111):
        return None

    buffer = ctypes.create_string_buffer(size.value)
    adapter = ctypes.cast(buffer, IpAdapterInfoPtr)
    if ip_helper.GetAdaptersInfo(adapter, ctypes.byref(size)) != 0:
        return None

    while adapter:
        info = adapter.contents
        address = ctypes.pointer(info.ip_address_list)
        while address:
            ip = address.contents.ip_address.value.decode("ascii", errors="ignore")
            if ip == local_ip:
                adapter_name = info.adapter_name.decode("ascii", errors="ignore")
                return rf"\Device\NPF_{adapter_name}"
            address = address.contents.next
        adapter = info.next
    return None


def _find_device(lib: ctypes.CDLL, local_ip: str) -> str:
    windows_device = _find_windows_device(local_ip)
    if windows_device:
        return windows_device

    devices = _PcapIfPtr()
    errbuf = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
    if lib.pcap_findalldevs(ctypes.byref(devices), errbuf) != 0:
        raise LibpcapUnavailable(errbuf.value.decode("utf-8", errors="replace"))

    try:
        device = devices
        available = []
        while device:
            entry = device.contents
            name = entry.name.decode("utf-8", errors="replace")
            addresses = entry.addresses
            while addresses:
                ip = _ipv4_from_sockaddr(addresses.contents.addr)
                if ip:
                    available.append((name, ip))
                    if ip == local_ip:
                        return name
                addresses = addresses.contents.next
            device = entry.next
    finally:
        lib.pcap_freealldevs(devices)

    details = ", ".join(f"{name}={ip}" for name, ip in available) or "no IPv4 capture devices"
    raise LibpcapUnavailable(f"no libpcap device owns local address {local_ip}; found {details}")


def _extract_ipv4_frame(frame: bytes, datalink: int) -> bytes | None:
    if datalink == DLT_EN10MB:
        if len(frame) < 14:
            return None
        offset = 14
        ether_type = struct.unpack_from("!H", frame, 12)[0]
        while ether_type in (0x8100, 0x88A8, 0x9100):
            if len(frame) < offset + 4:
                return None
            ether_type = struct.unpack_from("!H", frame, offset + 2)[0]
            offset += 4
        return frame[offset:] if ether_type == 0x0800 else None

    if datalink in (DLT_RAW_BSD, DLT_RAW):
        return frame

    if datalink in (DLT_NULL, DLT_LOOP):
        if len(frame) < 4:
            return None
        family_native = struct.unpack_from("=I", frame, 0)[0]
        family_network = struct.unpack_from("!I", frame, 0)[0]
        return frame[4:] if socket.AF_INET in (family_native, family_network) else None

    if datalink == DLT_LINUX_SLL:
        if len(frame) < 16 or struct.unpack_from("!H", frame, 14)[0] != 0x0800:
            return None
        return frame[16:]

    if datalink == DLT_LINUX_SLL2:
        if len(frame) < 20 or struct.unpack_from("!H", frame, 0)[0] != 0x0800:
            return None
        return frame[20:]

    raise LibpcapUnavailable(f"unsupported libpcap link-layer type {datalink}")


class LibpcapCapture:
    def __init__(self, local_ip: str) -> None:
        self.lib = _load_library()
        _configure_api(self.lib)
        self.device = _find_device(self.lib, local_ip)
        self.handle = ctypes.c_void_p()

        errbuf = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
        handle = self.lib.pcap_create(self.device.encode("utf-8"), errbuf)
        if not handle:
            raise LibpcapUnavailable(errbuf.value.decode("utf-8", errors="replace"))
        self.handle = ctypes.c_void_p(handle)

        try:
            self.lib.pcap_set_snaplen(self.handle, SNAP_LENGTH)
            self.lib.pcap_set_promisc(self.handle, 0)
            self.lib.pcap_set_timeout(self.handle, READ_TIMEOUT_MS)
            self.lib.pcap_set_buffer_size(self.handle, CAPTURE_BUFFER_SIZE)

            activation = self.lib.pcap_activate(self.handle)
            if activation < 0:
                raise LibpcapUnavailable(_pcap_error(self.lib, self.handle))

            program = _BpfProgram()
            filter_expression = f"host {local_ip} and (udp or tcp)".encode("ascii")
            if self.lib.pcap_compile(self.handle, ctypes.byref(program), filter_expression, 1, 0xFFFFFFFF) != 0:
                raise LibpcapUnavailable(_pcap_error(self.lib, self.handle))
            try:
                if self.lib.pcap_setfilter(self.handle, ctypes.byref(program)) != 0:
                    raise LibpcapUnavailable(_pcap_error(self.lib, self.handle))
            finally:
                self.lib.pcap_freecode(ctypes.byref(program))

            self.datalink = self.lib.pcap_datalink(self.handle)
        except Exception:
            self.close()
            raise

    def packets(self) -> Iterator[ParsedIpUdpPacket | None]:
        header = ctypes.POINTER(_PcapPacketHeader)()
        packet_data = ctypes.POINTER(ctypes.c_ubyte)()
        while self.handle:
            result = self.lib.pcap_next_ex(self.handle, ctypes.byref(header), ctypes.byref(packet_data))
            if result == 0:
                yield None
                continue
            if result == -2:
                return
            if result < 0:
                raise RuntimeError(_pcap_error(self.lib, self.handle))

            frame = ctypes.string_at(packet_data, header.contents.caplen)
            ipv4_packet = _extract_ipv4_frame(frame, self.datalink)
            if ipv4_packet is None:
                continue
            packet = parse_ipv4_packet(ipv4_packet)
            if packet is not None:
                yield packet

    def stats(self) -> CaptureStats | None:
        if not self.handle:
            return None
        stats = _PcapStat()
        if self.lib.pcap_stats(self.handle, ctypes.byref(stats)) != 0:
            return None
        return CaptureStats(stats.ps_recv, stats.ps_drop, stats.ps_ifdrop)

    def close(self) -> None:
        if self.handle:
            self.lib.pcap_close(self.handle)
            self.handle = ctypes.c_void_p()


def open_libpcap_capture(local_ip: str) -> LibpcapCapture:
    return LibpcapCapture(local_ip)
