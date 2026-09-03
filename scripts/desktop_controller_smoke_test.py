"""Manual smoke tests for Module 5 desktop control."""
from __future__ import annotations

import argparse
import time

from conduit.desktop import DesktopController


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["info", "move", "type", "hotkey", "scroll"])
    parser.add_argument("--x", type=int)
    parser.add_argument("--y", type=int)
    parser.add_argument("--text", default="Conduit desktop control is working.")
    args = parser.parse_args()

    desktop = DesktopController()
    print("Emergency stop: move the pointer rapidly to the top-left corner.")

    if args.action == "info":
        print("Screen:", desktop.screen_bounds())
        print("Mouse:", desktop.mouse_position())
        return

    if args.action == "move":
        if args.x is None or args.y is None:
            raise SystemExit("--x and --y are required for move.")
        print("This will move your mouse in 3 seconds. Press Ctrl+C to cancel.")
        time.sleep(3)
        print(desktop.move_mouse(args.x, args.y, duration=0.6))
        return

    if args.action == "type":
        print("Focus a safe text field now. Typing begins in 5 seconds. Press Ctrl+C to cancel.")
        time.sleep(5)
        print(desktop.type_text(args.text))
        return

    if args.action == "hotkey":
        print("This will press Ctrl+L in 5 seconds. Use it only with a browser focused. Press Ctrl+C to cancel.")
        time.sleep(5)
        print(desktop.hotkey(["ctrl", "l"]))
        return

    print("This will scroll down 4 steps in 5 seconds. Press Ctrl+C to cancel.")
    time.sleep(5)
    print(desktop.scroll(-4))


if __name__ == "__main__":
    main()
