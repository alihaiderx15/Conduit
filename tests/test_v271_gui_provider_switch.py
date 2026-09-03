from pathlib import Path

from conduit.code_helper.service import CodeHelperService


def root():
    return Path(__file__).resolve().parents[1]


def test_gui_contains_masked_gemini_and_openai_buttons():
    source = (root()/"conduit/gui/app.py").read_text(encoding="utf-8")
    assert 'QPushButton("GEMINI")' in source
    assert 'QPushButton("OPENAI")' in source
    assert 'QLineEdit.Password' in source
    assert 'self.runtime.switch_provider(provider, key)' in source


def test_typed_provider_switch_is_intercepted_before_agent():
    source = (root()/"conduit/gui/app.py").read_text(encoding="utf-8")
    send_start = source.index("    def _send_command")
    quick_start = source.index("    def _quick_command", send_start)
    send_block = source[send_start:quick_start]
    assert "provider_target = self._provider_switch_target(text)" in send_block
    assert "self._request_provider_switch(provider_target)" in send_block
    assert send_block.index("provider_target =") < send_block.index("self.runtime.submit(text)")


def test_runtime_uses_existing_model_discovery_and_hot_swap_backend():
    source = (root()/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    assert "models = await candidate.list_models()" in source
    assert "_choose_openai_model(models)" in source
    assert "await self.agent.switch_provider(" in source
    assert 'os.environ["GEMINI_API_KEY"] = api_key' in source
    assert 'os.environ["OPENAI_API_KEY"] = api_key' in source


def test_api_key_is_not_logged_by_provider_switch():
    source = (root()/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    handler = source[source.index("    async def _handle_provider_switch"):source.index("    def _deliver_answer")]
    assert 'api_key' in handler
    assert 'f"{api_key}' not in handler
    assert 'str(api_key)' not in handler


def test_code_fence_cleanup_handles_unmatched_trailing_fence():
    text = 'print("hello")\n```'
    assert CodeHelperService.strip_code_fences(text) == 'print("hello")'


def test_code_fence_cleanup_handles_standard_fenced_code():
    text = '```python\nprint("hello")\n```'
    assert CodeHelperService.strip_code_fences(text) == 'print("hello")'


def test_version_271():
    assert 'version = "3.1.8"' in (root()/"pyproject.toml").read_text(encoding="utf-8")
