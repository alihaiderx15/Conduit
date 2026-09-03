"""Console credential input with visible masking and no secret echo."""
from __future__ import annotations

import getpass
import sys


def masked_input(prompt: str, *, mask: str = "*") -> str:
    """Read a secret while showing one mask character per typed character.

    Windows uses msvcrt so users get visible feedback without exposing the key.
    Other platforms fall back to getpass because portable masked echo is not
    reliably available in the standard library.
    """
    if sys.platform != "win32":
        return getpass.getpass(prompt)

    import msvcrt

    print(prompt, end="", flush=True)
    chars: list[str] = []
    try:
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                print()
                return "".join(chars)
            if ch == "\003":  # Ctrl+C
                print()
                raise KeyboardInterrupt
            if ch == "\b":
                if chars:
                    chars.pop()
                    print("\b \b", end="", flush=True)
                continue
            # Ignore special-key prefix sequences (arrows/function keys).
            if ch in ("\x00", "\xe0"):
                msvcrt.getwch()
                continue
            if ch.isprintable():
                chars.append(ch)
                print(mask, end="", flush=True)
    finally:
        # Never retain or print the collected secret beyond the return value.
        pass
