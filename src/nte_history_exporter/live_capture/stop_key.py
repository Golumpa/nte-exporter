from __future__ import annotations

import os
import select
import sys


def _read_windows_key() -> None:
    import msvcrt

    key = msvcrt.getch()
    # Function and arrow keys are emitted as a two-byte sequence. Consume the
    # second byte so it cannot immediately satisfy the next key prompt.
    if key in {b"\x00", b"\xe0"}:
        msvcrt.getch()


def wait_for_keypress() -> None:
    """Wait for one key on an interactive terminal, or Enter on redirected input."""
    if os.name == "nt" and sys.stdin.isatty():
        _read_windows_key()
        return

    if not sys.stdin.isatty():
        try:
            input()
        except EOFError:
            pass
        return

    import termios
    import tty

    fd = sys.stdin.fileno()
    original_terminal = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        os.read(fd, 1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original_terminal)


class StopKeyMonitor:
    def __init__(self) -> None:
        self._windows = os.name == "nt"
        self._fd: int | None = None
        self._original_terminal = None

    def __enter__(self) -> StopKeyMonitor:
        if self._windows or not sys.stdin.isatty():
            return self

        import termios
        import tty

        self._fd = sys.stdin.fileno()
        self._original_terminal = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def pressed(self) -> bool:
        if self._windows:
            import msvcrt

            if not msvcrt.kbhit():
                return False
            _read_windows_key()
            return True

        if self._fd is None:
            return False
        readable, _, _ = select.select([self._fd], [], [], 0)
        if not readable:
            return False
        os.read(self._fd, 1)
        return True

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        if self._fd is None or self._original_terminal is None:
            return

        import termios

        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._original_terminal)
