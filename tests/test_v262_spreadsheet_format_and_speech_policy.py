
from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.conversation.session import ConversationSession
from conduit.file_processing import FileProcessingService
from conduit.speech_policy import LONG_ANSWER_NOTICE, speech_text_for_answer


def make_service(tmp_path):
    return FileProcessingService(state_path=tmp_path/"state.json")


@pytest.mark.asyncio
async def test_spreadsheet_format_returns_clean_capability_message(tmp_path, monkeypatch):
    import pandas as pd
    from conduit.conversation import session as session_mod

    p = tmp_path/"sales.xlsx"
    pd.DataFrame({"Revenue":[100,200]}).to_excel(p, index=False)
    service = make_service(tmp_path)
    service.register_dropped_file(p)
    monkeypatch.setattr(session_mod, "file_service", service)

    session = object.__new__(ConversationSession)
    session.agent = SimpleNamespace(loop=SimpleNamespace(provider=None, model="none"))
    session._file_context = {}

    assert ConversationSession._could_be_file_processing_request("Format this file")
    answer, report = await session._execute_file_processing_request("Format this file")
    assert report.success is False
    assert "Formatting isn't supported as a standalone spreadsheet action" in answer


def test_short_answer_is_spoken_fully():
    answer = "Discord is open and ready."
    assert speech_text_for_answer(answer) == answer


def test_exactly_50_words_is_spoken_fully():
    answer = " ".join(f"word{i}" for i in range(50))
    assert speech_text_for_answer(answer) == answer


def test_more_than_50_words_uses_notice_only():
    answer = " ".join(f"word{i}" for i in range(51))
    assert speech_text_for_answer(answer) == LONG_ANSWER_NOTICE
    assert len(LONG_ANSWER_NOTICE.split()) < 50


def test_runtime_keeps_full_chat_answer_and_separate_speech_channel():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    assert "self.signals.answer.emit(user, answer, success)" in source
    assert "speech_text_for_answer(answer, max_words=50)" in source
    assert "self.signals.speech.emit(speech)" in source


def test_version_262():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
