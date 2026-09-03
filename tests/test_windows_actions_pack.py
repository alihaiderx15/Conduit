
from conduit.tools.builtin import registry

def test_windows_action_pack_is_registered():
    names = {item.name for item in registry.all()}
    expected = {
        "files.info", "files.append_text", "clipboard.read", "clipboard.write",
        "system.active_window", "system.list_windows", "system.activate_window",
        "system.window_state",
    }
    assert expected <= names
