from pathlib import Path
from conduit.conversation.session import ConversationSession
from conduit.file_processing import FileProcessingService


def test_summary_doc_is_file_intent_with_active_doc(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod
    doc=tmp_path/'1.docx'; doc.write_bytes(b'fake')
    service=FileProcessingService(state_path=tmp_path/'state.json')
    service.register_dropped_file(doc)
    monkeypatch.setattr(session_mod, 'file_service', service)
    assert ConversationSession._could_be_file_processing_request('summarize this doc')
    assert ConversationSession._could_be_file_processing_request("can u tell me whats written in this in summary")


def test_file_router_precedes_system_router():
    root=Path(__file__).resolve().parents[1]
    src=(root/'conduit/conversation/session.py').read_text()
    ask=src[src.index('    async def ask'):src.index('    @classmethod\n    def _could_be_file_processing_request')]
    assert ask.index('if self._could_be_file_processing_request(clean):') < ask.index('if self._could_be_system_control_request(clean):')


def test_summary_has_deterministic_file_plan():
    root=Path(__file__).resolve().parents[1]
    src=(root/'conduit/conversation/session.py').read_text()
    assert 'FilePlan("summarize", "", {"save_file": save_summary_file})' in src


def test_version_256():
    root=Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/'pyproject.toml').read_text()
