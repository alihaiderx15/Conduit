
from pathlib import Path
from datetime import datetime

from conduit.memory import MemoryManager, ShortTermSessionMemory, LongTermMemoryLearner, SessionRecapManager
from conduit.proactive import ProactiveContextBuilder, ProactivePolicy, ProactiveTriggerEngine
from conduit.code_helper.service import CodeHelperService


def manager(tmp_path):
    return MemoryManager(tmp_path/'memory.sqlite3')


def test_short_term_memory_keeps_entire_session_and_clear_wipes_it():
    mem=ShortTermSessionMemory()
    for i in range(40): mem.add(f'user {i}', f'answer {i}')
    mem.add_event('tool.completed', '{"tool_name":"system.open_app","app":"discord"}')
    assert len(mem.turns)==40
    assert len(mem.events)==1
    context=mem.context_for('user 2', recent_turns=4, relevant_older=3)
    assert 'user 39' in context
    assert 'user 2' in context
    mem.clear()
    assert mem.turns==[]
    assert mem.events==[]


def test_explicit_code_directory_directive_is_persistent(tmp_path):
    mgr=manager(tmp_path)
    learner=LongTermMemoryLearner(mgr)
    learner.observe('always save the coding files you generate in D drive')
    assert mgr.directive('code','output_directory') == 'D:\\'
    mgr.close()


def test_repeated_youtube_channels_are_ranked(tmp_path):
    mgr=manager(tmp_path)
    learner=LongTermMemoryLearner(mgr)
    learner.observe('play latest video from Gamer Nexus on youtube')
    learner.observe('play latest video from Gamer Nexus on youtube')
    learner.observe('play latest video from Tech World on youtube')
    top=mgr.top_behaviors('youtube_channel',limit=2)
    assert top[0].value == 'Gamer Nexus'
    assert top[0].count >= 2
    mgr.close()


def test_session_recap_is_one_time_resume_context(tmp_path):
    mgr=manager(tmp_path)
    session=ShortTermSessionMemory(); session.add('open discord','Opened Discord.')
    recaps=SessionRecapManager(mgr)
    assert recaps.summarize_and_store(session)
    first=recaps.resume_context(consume=True)
    second=recaps.resume_context(consume=True)
    assert 'open discord' in first
    assert second == ''
    mgr.close()


def test_behavior_and_directive_survive_manager_restart(tmp_path):
    path=tmp_path/'memory.sqlite3'
    mgr=MemoryManager(path); learner=LongTermMemoryLearner(mgr)
    learner.observe('always save coding files in D drive')
    learner.observe('play latest video from Test Channel on youtube')
    mgr.close()
    mgr2=MemoryManager(path)
    assert mgr2.directive('code','output_directory') == 'D:\\'
    assert mgr2.top_behaviors('youtube_channel',limit=1)[0].value == 'Test Channel'
    mgr2.close()


def test_code_helper_can_generate_into_memory_selected_directory(tmp_path):
    service=CodeHelperService()
    target=service.default_generated_path(language='python',prompt='generate hello',base_dir=tmp_path/'D-drive')
    assert target.parent == (tmp_path/'D-drive').resolve()


def test_proactive_engine_uses_favorite_channel_after_idle(tmp_path, monkeypatch):
    mgr=manager(tmp_path)
    mgr.repository.increment_behavior('youtube_channel','Favorite Channel',score_delta=3)
    policy=ProactivePolicy(idle_seconds=0,cooldown_seconds=999999,quiet_start_hour=23,quiet_end_hour=7)
    engine=ProactiveTriggerEngine(ProactiveContextBuilder(mgr),policy=policy)
    msg=engine.evaluate(session_turns=4,now=datetime(2026,8,23,12,0,0))
    assert 'Favorite Channel' in msg
    assert engine.evaluate(session_turns=4,now=datetime(2026,8,23,12,0,1)) == ''
    mgr.close()


def test_memory_schema_migrated_to_v2(tmp_path):
    mgr=manager(tmp_path)
    version=mgr.database.connection.execute('PRAGMA user_version').fetchone()[0]
    assert version == 2
    mgr.close()


def test_gui_has_wireless_display_dpi_guard():
    root=Path(__file__).resolve().parents[1]
    source=(root/'conduit/gui/app.py').read_text(encoding='utf-8')
    assert 'screenChanged.connect' in source
    assert '_apply_screen_geometry' in source
    assert 'HighDpiScaleFactorRoundingPolicy.PassThrough' in source


def test_runtime_saves_session_recap_and_runs_proactive_engine():
    root=Path(__file__).resolve().parents[1]
    source=(root/'conduit/gui/runtime.py').read_text(encoding='utf-8')
    assert 'self.conversation.finalize_session()' in source
    assert 'ProactiveTriggerEngine' in source
    assert 'proactive.triggered' in source
    assert 'MemoryWriteMode.AUTO_SAFE' in source


def test_version_300():
    root=Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/'pyproject.toml').read_text(encoding='utf-8')
