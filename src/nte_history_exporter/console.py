from __future__ import annotations

import os
import sys

from nte_history_exporter.constants import EXPORTER_VERSION, GAME_NAME

WIDTH = 58

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
CYAN = "\x1b[36m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"

_ansi: bool | None = None


def _enable_ansi() -> bool:
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        return bool(kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING))
    except Exception:
        return False


def ansi_enabled() -> bool:
    global _ansi
    if _ansi is None:
        _ansi = _enable_ansi()
    return _ansi


def style(text: str, *codes: str) -> str:
    if not codes or not ansi_enabled():
        return text
    return "".join(codes) + text + RESET


def rule(char: str = "-") -> str:
    return style(char * WIDTH, DIM)


def print_banner() -> None:
    print()
    print(rule("="))
    print(style(f"  NTE History Exporter  v{EXPORTER_VERSION}", BOLD, CYAN))
    print(style(f"  {GAME_NAME} pull history -> tracker JSON", DIM))
    print(rule("="))


def print_live_instructions(local_ip: str, backend: str = "windows_raw", detail: str = "") -> None:
    print()
    print(style("  Listening on ", DIM) + style(local_ip, BOLD))
    backend_detail = f" ({detail})" if detail and detail != local_ip else ""
    print(style(f"  Capture backend: {backend}{backend_detail}", DIM))
    print()
    print(style("  How to export your pull history", BOLD))
    print("    1. For automatic user UID detection, start this tool")
    print("       before pressing Start on the game's main menu.")
    print("       Already in game? You can still capture history;")
    print("       the tool will ask for your UID if it cannot detect it.")
    print("    2. Open a supported history screen:")
    print(style("         Monopoly  >  Standard Board history", CYAN))
    print(style("         Monopoly  >  Limited Character Board history", CYAN))
    print(style("         Gashapon  >  Arc Miracle Box history", CYAN))
    print("    3. Start at page 1 and scroll down through every page")
    print("       you want exported.")
    print("    4. Scroll one page past where you plan to stop so the")
    print("       last pull group can be confirmed as complete.")
    print("    5. You can open several boards in the same session.")
    print()
    print(style("  Waiting for history pages... press any key here when done.", BOLD, GREEN))
    print(rule())


def print_page_captured(label: str, page: int | None, *, recaptured: bool = False) -> None:
    action = "recaptured" if recaptured else "page"
    print(style("  + ", GREEN, BOLD) + label + style(f"  {action} {page}", DIM))


def print_missing_pages(label: str, pages: list[int], reasons: dict[int, str] | None = None) -> None:
    page_list = ", ".join(str(page) for page in pages)
    print(style("  ! ", YELLOW, BOLD) + f"{label} missing page(s): {page_list}.")
    if reasons:
        for page in pages:
            print(style(f"    Page {page}: {reasons[page]}.", DIM))
    print("    Close and reopen this history board, then scroll down again.")


def print_page_gap_recovered(label: str) -> None:
    print(style("  + ", GREEN, BOLD) + f"{label} page gap recovered.")


def print_capture_stats(received: int, dropped: int, interface_dropped: int) -> None:
    text = (
        f"Capture stats: processed {received}, buffer dropped {dropped}, "
        f"interface dropped {interface_dropped}"
    )
    if dropped or interface_dropped:
        print(style(f"  ! {text}", YELLOW, BOLD))
    else:
        print(style(f"  {text}", DIM))


def print_capture_fallback(reason: str) -> None:
    print(style("  ! Npcap unavailable; using Windows raw capture.", YELLOW))
    print(style(f"    {reason}", DIM))


def print_results_header() -> None:
    print()
    print(rule())
    print(style("  Results", BOLD))
    print(rule())


def print_export_summary(name: str, decoded: int, exported: int, skipped: int) -> None:
    counts = [
        style(f"decoded {decoded}", DIM),
        style(f"exported {exported}", GREEN, BOLD),
        style(f"skipped {skipped}", YELLOW if skipped else DIM),
    ]
    print(f"  {name:<30}" + "   ".join(counts))


def print_warning(code: str, reason: str, records: int | None = None) -> None:
    suffix = f" ({records} records)" if records is not None else ""
    print(style(f"  ! {code}: {reason}{suffix}", YELLOW))


def print_note(text: str) -> None:
    print(style(f"  {text}", DIM))


def print_success(text: str) -> None:
    print(style(f"  {text}", GREEN, BOLD))


def print_problem(text: str) -> None:
    print(style(f"  {text}", YELLOW, BOLD))


def prompt_user_uid() -> str | None:
    print()
    print_problem("User UID was not detected in this capture.")
    print_note("Enter your NTE user UID so the export can be named and linked correctly.")
    print_note("Leaving this blank may prevent import on some trackers.")
    value = input("  User UID: ").strip()
    return value or None
