"""Safe General PC Agent v1.1 Windows Actions Pack smoke test."""
import sys
from conduit.tools.builtin import registry

def main():
    names = {x.name for x in registry.all()}
    expected = [
        "files.info", "files.append_text", "clipboard.read", "clipboard.write",
        "system.active_window", "system.list_windows", "system.activate_window",
        "system.window_state",
    ]
    missing = [x for x in expected if x not in names]
    if missing:
        raise SystemExit(f"Missing actions: {missing}")
    print("WINDOWS ACTIONS PACK")
    for name in expected:
        print(" OK", name)
    print("WINDOWS ACTIONS PACK SMOKE TEST: PASS")

if __name__ == "__main__":
    main()
