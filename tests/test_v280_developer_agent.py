
from pathlib import Path
import json
import sys
import pytest

from conduit.dev_agent import DeveloperProjectService, ProjectPlan, DevErrorCategory
from conduit.conversation.session import ConversationSession


def make_service(tmp_path):
    service = DeveloperProjectService(timeout_seconds=5)
    service._active_project = None
    return service


def test_create_and_inspect_python_project(tmp_path):
    service = make_service(tmp_path)
    root = tmp_path/"demo"
    plan = ProjectPlan(
        name="demo",
        language="python",
        entry_point="main.py",
        files=[
            {"path":"main.py","purpose":"entry"},
            {"path":"utils.py","purpose":"helper"},
            {"path":"tests/test_utils.py","purpose":"tests"},
        ],
    )
    created = service.create_from_files(
        project_name="demo",
        path=str(root),
        plan=plan,
        files={
            "main.py": 'from utils import add\nprint(add(2, 3))',
            "utils.py": 'def add(a, b):\n    return a + b',
            "tests/test_utils.py": 'import unittest\nfrom utils import add\nclass T(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(1,2),3)',
        },
    )
    assert created == root.resolve()
    info = service.inspect(root)
    assert info.kind.value == "python"
    assert info.entry_point == "main.py"
    assert "utils.py" in info.files
    assert (root/".conduit_project.json").exists()


def test_project_runner_captures_output(tmp_path):
    service = make_service(tmp_path)
    root = tmp_path/"run-demo"
    service.create_from_files(
        project_name="run-demo",
        path=str(root),
        plan={"entry_point":"main.py","language":"python"},
        files={"main.py": 'print("Hello project")'},
    )
    result = service.run_project(root)
    assert result.success is True
    assert "Hello project" in result.stdout


def test_project_patch_confined_and_backed_up(tmp_path):
    service = make_service(tmp_path)
    root = tmp_path/"patch-demo"
    service.create_from_files(
        project_name="patch-demo",
        path=str(root),
        files={"main.py": 'print("old")'},
    )
    written = service.patch_files({"main.py": 'print("new")'}, root)
    assert written
    assert 'print("new")' in (root/"main.py").read_text()
    backups = list((root/".conduit_backups").rglob("main.py"))
    assert backups
    assert 'print("old")' in backups[0].read_text()


def test_project_path_escape_is_rejected(tmp_path):
    service = make_service(tmp_path)
    root = tmp_path/"safe"
    root.mkdir()
    service.set_active_project(root)
    with pytest.raises(Exception):
        service.patch_files({"../escape.py":"print(1)"})


def test_inspection_ignores_node_modules(tmp_path):
    service = make_service(tmp_path)
    root = tmp_path/"node-demo"
    service.create_from_files(
        project_name="node-demo",
        path=str(root),
        files={
            "package.json": '{"scripts":{"start":"node index.js"}}',
            "index.js": 'console.log("ok")',
        },
    )
    (root/"node_modules/pkg").mkdir(parents=True)
    (root/"node_modules/pkg/index.js").write_text("ignored")
    files = service.list_project_files(root)
    assert "index.js" in files
    assert not any("node_modules" in x for x in files)


def test_dev_request_is_distinct_from_single_file_request(tmp_path, monkeypatch):
    from conduit.conversation import session as sm
    service = make_service(tmp_path)
    monkeypatch.setattr(sm, "dev_service", service)

    session = object.__new__(ConversationSession)
    assert session._could_be_dev_request("build a multi-file python todo project")
    assert session._could_be_dev_request("plan a flask project")


def test_dev_tools_registered():
    from conduit.tools.builtin import registry
    names = {item.name for item in registry.all()}
    required = {
        "dev.plan_project",
        "dev.create_project",
        "dev.inspect_project",
        "dev.install_dependencies",
        "dev.run_project",
        "dev.run_tests",
        "dev.analyze_error",
        "dev.patch_files",
        "dev.open_editor",
    }
    assert required <= names


def test_required_dependency_command_is_restricted(tmp_path):
    service = make_service(tmp_path)
    root = tmp_path/"dep-demo"
    service.create_from_files(
        project_name="dep-demo",
        path=str(root),
        files={
            "requirements.txt":"requests==2.32.3",
            "main.py":"print('ok')",
        },
        plan={"entry_point":"main.py","language":"python"},
    )
    argv, cwd = service.dependency_install_command(root)
    assert argv[:4] == [sys.executable, "-m", "pip", "install"]
    assert argv[-2:] == ["-r", "requirements.txt"]
    assert cwd == root.resolve()


def test_version_280():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
