
from conduit.actions import UnifiedActionRegistry, register_default_actions
from conduit.tools.builtin import registry

def test_v12_structured_actions_registered():
    names={item.name for item in registry.all()}
    assert {
        "files.delete","files.list_recent","system.process_info",
        "system.window_bounds","system.move_resize_window",
    } <= names

def test_v12_desktop_actions_registered():
    actions=register_default_actions(UnifiedActionRegistry(registry))
    names={item.name for item in actions.all()}
    assert {
        "desktop.click_xy","desktop.move_mouse",
        "desktop.mouse_position","desktop.screen_bounds",
    } <= names

def test_destructive_delete_requires_confirmation():
    assert registry.get("files.delete").risk.value == "confirm"
