from pathlib import Path
import asyncio
import pytest

from conduit.core.progress_watchdog import run_with_progress_watchdog, ProgressStalledError


def test_gui_uses_splitters_for_hard_panel_boundaries():
    root = Path(__file__).resolve().parents[1]
    source = (root/'conduit/gui/app.py').read_text(encoding='utf-8')
    assert 'QSplitter(Qt.Horizontal)' in source
    assert 'QSplitter(Qt.Vertical)' in source
    assert 'self.main_splitter.setChildrenCollapsible(False)' in source
    assert 'self._apply_responsive_splitter_sizes' in source


def test_provider_buttons_are_responsive_grid_buttons():
    root = Path(__file__).resolve().parents[1]
    source = (root/'conduit/gui/app.py').read_text(encoding='utf-8')
    assert 'button.setObjectName("providerButton")' in source
    assert 'button.setMinimumWidth(0)' in source
    assert 'QSizePolicy.Ignored' in source


def test_button_theme_has_visible_boundaries_and_hover():
    root = Path(__file__).resolve().parents[1]
    source = (root/'conduit/gui/theme.py').read_text(encoding='utf-8')
    assert 'QPushButton#providerButton' in source
    assert 'QPushButton#providerButton:hover' in source
    assert 'QSplitter#mainSplitter::handle' in source
    assert 'border: 1px solid #36517D' in source


@pytest.mark.asyncio
async def test_watchdog_has_no_total_timeout_when_progress_continues():
    checks = []

    async def operation(heartbeat):
        for _ in range(4):
            await asyncio.sleep(0.02)
            heartbeat(5, 'progress')
        return 'done'

    async def on_check(snapshot):
        checks.append(snapshot)

    result = await run_with_progress_watchdog(
        operation,
        check_interval=0.01,
        initial_missed_checks=2,
        active_missed_checks=2,
        on_check=on_check,
    )
    assert result == 'done'


@pytest.mark.asyncio
async def test_watchdog_cancels_stalled_task():
    async def operation(heartbeat):
        heartbeat(1, 'started')
        await asyncio.sleep(1)
        return 'never'

    with pytest.raises(ProgressStalledError):
        await run_with_progress_watchdog(
            operation,
            check_interval=0.02,
            initial_missed_checks=2,
            active_missed_checks=1,
        )


def test_code_and_dev_use_progress_watchdog_not_fixed_timeout():
    root = Path(__file__).resolve().parents[1]
    session = (root/'conduit/conversation/session.py').read_text(encoding='utf-8')
    dev = (root/'conduit/dev_agent/agent.py').read_text(encoding='utf-8')
    assert 'run_with_progress_watchdog' in session
    assert 'overall_timeout="unlimited"' in session
    assert 'run_with_progress_watchdog' in dev
    assert 'asyncio.wait_for(' not in dev[dev.index('async def model_text'):dev.index('def strip_json_fence')]


def test_version_316():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/'pyproject.toml').read_text(encoding='utf-8')
