
"""Registration/safety smoke test for General PC Agent v1.2."""
from conduit.actions import UnifiedActionRegistry, register_default_actions
from conduit.tools.builtin import registry

def main():
    actions=register_default_actions(UnifiedActionRegistry(registry))
    names={item.name for item in actions.all()}
    expected=[
        "files.delete","files.list_recent","system.process_info",
        "system.window_bounds","system.move_resize_window",
        "desktop.click_xy","desktop.move_mouse","desktop.mouse_position","desktop.screen_bounds",
    ]
    missing=[name for name in expected if name not in names]
    if missing:
        raise SystemExit(f"Missing v1.2 actions: {missing}")
    if registry.get("files.delete").risk.value != "confirm":
        raise SystemExit("files.delete must require confirmation.")
    print("GENERAL PC AGENT V1.2 ACTION PACK")
    for name in expected:
        print(" OK",name)
    print("DELETE CONFIRMATION: OK")
    print("GENERAL PC AGENT V1.2 SMOKE TEST: PASS")

if __name__=="__main__":
    main()
