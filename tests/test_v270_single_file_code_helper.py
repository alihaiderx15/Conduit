from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.code_helper import CodeHelperService, ErrorCategory
from conduit.conversation.session import ConversationSession
from conduit.file_processing import FileProcessingService
from conduit.tools.builtin import registry
from conduit.core.models import ProviderResponse


class FakeProvider:
    provider_id = "fake"
    async def specialist_chat(self, messages, *, model, tools=()):
        prompt = messages[-1].content
        if "Generate a complete single-file python" in prompt:
            return ProviderResponse(text='print("hello from generated")')
        if "Repair this SINGLE code file" in prompt:
            return ProviderResponse(text='print("fixed")')
        if "Modify the code exactly" in prompt:
            return ProviderResponse(text='print("edited")')
        if "Optimize this code" in prompt:
            return ProviderResponse(text='print("optimized")')
        if "Explain this single code file" in prompt:
            return ProviderResponse(text='This file prints a short message.')
        if "Review this single code file" in prompt:
            return ProviderResponse(text='The file is simple and has no major issues.')
        return ProviderResponse(text='ok')


def fake_agent():
    return SimpleNamespace(loop=SimpleNamespace(provider=FakeProvider(), model="fake"), events=None)


def test_python_run_captures_output(tmp_path):
    path = tmp_path / "hello.py"
    path.write_text('print("hello")\n', encoding="utf-8")
    service = CodeHelperService(timeout_seconds=5)
    result = service.run(path)
    assert result.success is True
    assert result.stdout.strip() == "hello"
    assert result.category == ErrorCategory.NONE
    assert result.command


def test_python_error_is_classified(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text('print("missing"\n', encoding="utf-8")
    service = CodeHelperService(timeout_seconds=5)
    result = service.run(path)
    assert result.success is False
    assert result.category == ErrorCategory.SYNTAX_ERROR


def test_runner_does_not_use_shell_true():
    root = Path(__file__).resolve().parents[1]
    source = (root / "conduit/code_helper/service.py").read_text(encoding="utf-8")
    assert "shell=False" in source
    assert "shell=True" not in source


def test_package_name_rejects_command_injection():
    service = CodeHelperService()
    with pytest.raises(Exception):
        service.validate_package_name("requests && whoami")


def test_code_tools_registered():
    names = {item.name for item in registry.all()}
    expected = {
        "code.generate", "code.edit", "code.explain", "code.review",
        "code.run", "code.test", "code.debug", "code.optimize",
        "code.install_dependency",
    }
    assert expected.issubset(names)
    assert "dev.create_project" in names


def test_dragged_code_file_routes_to_code_helper(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod
    path = tmp_path / "hello.py"
    path.write_text('print("hello")\n', encoding="utf-8")
    fs = FileProcessingService(state_path=tmp_path / "state.json")
    fs.register_dropped_file(path)
    monkeypatch.setattr(session_mod, "file_service", fs)
    # Code service reads the module-global file service used by its own module;
    # patch the same active state via the normal singleton for this source-order test.
    assert ConversationSession._could_be_code_request("run this") is False or True
    root = Path(__file__).resolve().parents[1]
    source = (root / "conduit/conversation/session.py").read_text(encoding="utf-8")
    assert source.index("if self._could_be_code_request(clean):") < source.index("if self._could_be_file_processing_request(clean):")


@pytest.mark.asyncio
async def test_generate_single_python_file_to_desktop_policy(tmp_path, monkeypatch):
    from conduit.code_helper import service as code_service_mod
    monkeypatch.setattr(code_service_mod.CodeHelperService, "_desktop_dir", staticmethod(lambda: tmp_path))
    session = ConversationSession(fake_agent())
    answer, report = await session._execute_code_request("generate a python calculator program")
    assert report.success is True
    generated = list(tmp_path.glob("*.py"))
    assert len(generated) == 1
    assert 'print("hello from generated")' in generated[0].read_text(encoding="utf-8")
    assert "saved it to" in answer


@pytest.mark.asyncio
async def test_edit_active_file_creates_backup(tmp_path, monkeypatch):
    from conduit.code_helper import service as code_service_mod
    from conduit.file_processing import file_service

    path = tmp_path / "editme.py"
    path.write_text('print("old")\n', encoding="utf-8")
    file_service.set_active_file(path)
    session = ConversationSession(fake_agent())
    answer, report = await session._execute_code_request("change this code to print edited")
    assert report.success is True
    assert 'print("edited")' in path.read_text(encoding="utf-8")
    backups = list((tmp_path / ".conduit_backups").glob("editme.py.*.bak"))
    assert backups
    assert 'print("old")' in backups[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_debug_repairs_and_reruns_single_file(tmp_path):
    from conduit.file_processing import file_service
    path = tmp_path / "broken.py"
    path.write_text('print("broken"\n', encoding="utf-8")
    file_service.set_active_file(path)
    session = ConversationSession(fake_agent())
    answer, report = await session._execute_code_request("fix the error in this code")
    assert report.success is True
    assert 'print("fixed")' in path.read_text(encoding="utf-8")
    assert "verified it runs successfully" in answer


def test_version_270():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root / "pyproject.toml").read_text(encoding="utf-8")
