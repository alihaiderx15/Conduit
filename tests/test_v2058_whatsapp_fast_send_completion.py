
from pathlib import Path

def test_whatsapp_skips_post_send_vision_but_keeps_pre_send_verification():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit"/"conversation"/"session.py").read_text(encoding="utf-8")
    block = source[source.index("# Verify the WHOLE approved draft"):source.index("def _could_be_youtube_request")]
    # Pre-send safety is preserved.
    assert "DRAFT_PRESENT" in block
    assert 'service_press(self.agent, service, client, "enter")' in block
    # WhatsApp then completes through the fast deterministic branch.
    assert 'if service == "whatsapp":' in block
    assert '"seconds": 0.25' in block
    # Sent-bubble vision remains only in the non-WhatsApp branch.
    fast_start = block.index('if service == "whatsapp":')
    else_start = block.index("else:", fast_start)
    whatsapp_fast = block[fast_start:else_start]
    assert "SENT_PRESENT" not in whatsapp_fast
    assert "compact_messaging_check" not in whatsapp_fast

def test_project_version_is_2058():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
