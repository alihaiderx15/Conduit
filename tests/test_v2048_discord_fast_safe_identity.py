from types import SimpleNamespace
from pathlib import Path
import pytest

from conduit.messaging import service as ms


@pytest.mark.asyncio
async def test_discord_display_name_only_match_stops_before_open(monkeypatch):
    pressed = []

    async def fake_foreground(*args, **kwargs):
        return "Discord"

    async def fake_description(agent, prompt):
        return SimpleNamespace(description="USER | Uzair | random.uzair")

    async def fake_press(agent, service, client, key):
        pressed.append(key)

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ms, "ensure_service_foreground", fake_foreground)
    monkeypatch.setattr(ms, "observe_messaging_description", fake_description)
    monkeypatch.setattr(ms, "service_press", fake_press)
    monkeypatch.setattr(ms, "emit_messaging_stage", noop)

    with pytest.raises(RuntimeError) as exc:
        await ms.open_matching_discord_recipient(
            SimpleNamespace(tools=SimpleNamespace(execute=None)),
            {"mode": "desktop"},
            "uzair",
        )

    text = str(exc.value)
    assert "@random.uzair" in text
    assert "won't guess" in text
    assert pressed == []


@pytest.mark.asyncio
async def test_discord_exact_username_match_opens_keyboard_only(monkeypatch):
    pressed = []

    async def fake_foreground(*args, **kwargs):
        return "Discord"

    async def fake_description(agent, prompt):
        return SimpleNamespace(
            description=(
                "USER | Uzair | otheruser\n"
                "USER | Uzair Khan | uzair\n"
                "USER | Someone | someone"
            )
        )

    async def fake_press(agent, service, client, key):
        pressed.append(key)

    async def noop(*args, **kwargs):
        return None

    class Tools:
        async def execute(self, call, confirmed=False):
            return SimpleNamespace(success=True, data={})

    monkeypatch.setattr(ms, "ensure_service_foreground", fake_foreground)
    monkeypatch.setattr(ms, "observe_messaging_description", fake_description)
    monkeypatch.setattr(ms, "service_press", fake_press)
    monkeypatch.setattr(ms, "emit_messaging_stage", noop)

    result = await ms.open_matching_discord_recipient(
        SimpleNamespace(tools=Tools()), {"mode": "desktop"}, "@uzair"
    )
    assert result["username"] == "uzair"
    assert result["index"] == 2
    assert pressed == ["down", "enter"]


def test_discord_fast_path_reduces_fixed_waits_and_skips_dm_home_vision():
    source = Path(ms.__file__).read_text(encoding="utf-8")
    block = source[source.index("async def open_contact_search"):source.index("async def service_press")]
    discord = block[block.index('if service == "discord"'):block.index('await emit_messaging_stage', block.index('if service == "discord"'))]
    assert "ensure_discord_direct_messages" not in discord
    assert 'seconds": 2.0' in discord
    assert "compact_messaging_check" not in discord


def test_version_is_2050():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert 'version = "3.1.8"' in pyproject.read_text(encoding="utf-8")
