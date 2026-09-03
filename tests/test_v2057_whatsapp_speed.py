
from pathlib import Path

def test_whatsapp_readiness_poll_is_one_second():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit"/"conversation"/"session.py").read_text(encoding="utf-8")
    block = source[source.index("async def _prepare_messaging_client"):source.index("async def _resolve_messaging_contact")]
    assert "poll_seconds=1.0" in block

def test_whatsapp_search_uses_fast_deterministic_path():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit"/"messaging"/"service.py").read_text(encoding="utf-8")
    block = source[source.index("async def open_contact_search"):source.index("async def service_press")]
    whatsapp = block[block.index('if service == "whatsapp"'):]
    assert '("ctrl", "f")' in whatsapp
    assert '"seconds": 1.0' in whatsapp
    # compact vision belongs only to the generic service path after WhatsApp returns
    fast = whatsapp[:whatsapp.index("return True")+len("return True")]
    assert "compact_messaging_check" not in fast

def test_whatsapp_result_selection_skips_redundant_results_vision():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit"/"conversation"/"session.py").read_text(encoding="utf-8")
    block = source[source.index('elif service == "whatsapp"'):source.index("        else:", source.index('elif service == "whatsapp"'))]
    assert 'service_press(self.agent, service, client, "enter")' in block
    assert "compact_messaging_check" not in block
    assert '"seconds": 1.0' in block
