
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Iterable

from conduit.code_helper.models import ErrorCategory
from conduit.code_helper import code_service
from .models import DevErrorCategory, DevRunResult, ProjectInfo, ProjectKind, ProjectPlan


class DeveloperAgentError(RuntimeError):
    pass


IGNORED_DIRS = {
    ".git", ".idea", ".vscode", "__pycache__", ".pytest_cache", ".mypy_cache",
    "node_modules", ".venv", "venv", "dist", "build", ".next", ".cache",
}
TEXT_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".html", ".css", ".scss",
    ".md", ".txt", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".env.example",
    ".c", ".h", ".cpp", ".hpp", ".java", ".cs", ".go", ".rs", ".sql",
}
SAFE_PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
SAFE_REL_PATH = re.compile(r"^[A-Za-z0-9_./@+\- ]{1,240}$")


class DeveloperProjectService:
    """Mechanical backend for Conduit's multi-file developer specialist.

    All file edits are confined to one active project root. Project execution
    uses explicit argv lists, ``shell=False``, output limits and timeouts.
    This is a restricted local runner, not a complete OS/container sandbox.
    """

    def __init__(self, *, timeout_seconds: float = 30.0, output_limit: int = 20000) -> None:
        self.timeout_seconds = max(2.0, float(timeout_seconds))
        self.output_limit = max(2000, int(output_limit))
        self._active_project: Path | None = None

    @staticmethod
    def desktop_dir() -> Path:
        for candidate in (Path.home()/"Desktop", Path.home()/"OneDrive"/"Desktop"):
            if candidate.exists() and candidate.is_dir():
                return candidate.resolve()
        fallback = Path.home()/"Desktop"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback.resolve()

    @staticmethod
    def safe_project_name(text: str) -> str:
        words = re.findall(r"[A-Za-z0-9]+", str(text or ""))
        stop = {
            "create","generate","build","make","project","application","app","website",
            "a","an","the","for","me","please","using","with","in",
        }
        useful = [w.casefold() for w in words if w.casefold() not in stop]
        name = "-".join(useful[:5]) or "conduit-project"
        return name[:72]

    def default_project_path(self, name: str, *, base_dir: str | Path | None = None) -> Path:
        name = self.safe_project_name(name)
        directory = Path(base_dir).expanduser().resolve() if base_dir else self.desktop_dir()
        directory.mkdir(parents=True, exist_ok=True)
        root = directory/name
        if not root.exists():
            return root
        for index in range(2, 1000):
            candidate = root.with_name(f"{root.name}-{index}")
            if not candidate.exists():
                return candidate
        raise DeveloperAgentError("Could not choose a free project folder on the Desktop.")

    def set_active_project(self, path: str | Path) -> Path:
        root = Path(path).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise DeveloperAgentError(f"Project folder does not exist: {root}")
        self._active_project = root
        return root

    def active_project(self) -> Path | None:
        if self._active_project is not None and self._active_project.exists():
            return self._active_project
        active_code = code_service.active_code_file()
        if active_code is not None:
            # If a code file lives inside a generated Conduit project, discover
            # the nearest marker without treating every parent directory as a project.
            for parent in [active_code.parent, *active_code.parents]:
                if (parent/".conduit_project.json").exists():
                    self._active_project = parent.resolve()
                    return self._active_project
        return None

    def resolve_project(self, path: str | Path | None = None) -> Path:
        if path not in {None, ""}:
            return self.set_active_project(path)
        root = self.active_project()
        if root is None:
            raise DeveloperAgentError(
                "No active project is set. Create a project first or provide its folder path."
            )
        return root

    @staticmethod
    def _safe_relpath(value: str) -> Path:
        raw = str(value or "").replace("\\", "/").strip().lstrip("/")
        if not raw or not SAFE_REL_PATH.fullmatch(raw):
            raise DeveloperAgentError(f"Unsafe project-relative path: {value!r}")
        rel = Path(raw)
        if rel.is_absolute() or ".." in rel.parts:
            raise DeveloperAgentError(f"Project path may not escape the workspace: {value!r}")
        return rel

    @staticmethod
    def _inside(root: Path, path: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    def write_files(
        self,
        root: str | Path,
        files: dict[str, str],
        *,
        overwrite: bool = False,
        backup_existing: bool = True,
    ) -> list[Path]:
        project = Path(root).expanduser().resolve()
        project.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for rel_name, content in files.items():
            rel = self._safe_relpath(rel_name)
            target = (project/rel).resolve()
            if not self._inside(project, target):
                raise DeveloperAgentError(f"Refusing to write outside project: {rel_name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and not overwrite:
                raise DeveloperAgentError(f"Project file already exists: {rel_name}")
            if target.exists() and backup_existing:
                backup_dir = project/".conduit_backups"/time.strftime("%Y%m%d-%H%M%S")
                backup = backup_dir/rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            target.write_text(str(content).rstrip()+"\n", encoding="utf-8")
            written.append(target)
        self._active_project = project
        return written

    def create_from_files(
        self,
        *,
        project_name: str,
        files: dict[str, str],
        plan: ProjectPlan | dict | None = None,
        path: str = "",
        base_dir: str | Path | None = None,
    ) -> Path:
        if path:
            root = Path(path).expanduser().resolve()
            if root.exists() and any(root.iterdir()):
                raise DeveloperAgentError(
                    "Refusing to create a new project inside a non-empty folder."
                )
        else:
            root = self.default_project_path(project_name, base_dir=base_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.write_files(root, files, overwrite=False, backup_existing=False)

        payload = plan.as_dict() if isinstance(plan, ProjectPlan) else dict(plan or {})
        payload.setdefault("name", root.name)
        payload["created_by"] = "Conduit Developer Agent"
        (root/".conduit_project.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._active_project = root
        return root

    def list_project_files(self, root: str | Path | None = None, *, limit: int = 300) -> list[str]:
        project = self.resolve_project(root)
        rows: list[str] = []
        for path in sorted(project.rglob("*")):
            try:
                rel = path.relative_to(project)
            except ValueError:
                continue
            if any(part in IGNORED_DIRS for part in rel.parts):
                continue
            if path.is_file():
                rows.append(rel.as_posix())
                if len(rows) >= limit:
                    break
        return rows

    def read_project_text(
        self,
        root: str | Path | None = None,
        *,
        per_file_limit: int = 16000,
        total_limit: int = 80000,
    ) -> str:
        project = self.resolve_project(root)
        chunks: list[str] = []
        total = 0
        for rel_name in self.list_project_files(project):
            path = project/rel_name
            if path.name == ".conduit_project.json":
                continue
            if path.suffix.casefold() not in TEXT_SUFFIXES and path.name not in {
                "Dockerfile","Makefile","requirements.txt","package.json","pyproject.toml"
            }:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            excerpt = text[:per_file_limit]
            block = f"\n===== FILE: {rel_name} =====\n{excerpt}\n"
            if total + len(block) > total_limit:
                break
            chunks.append(block)
            total += len(block)
        return "".join(chunks)

    def detect_kind(self, root: str | Path | None = None) -> ProjectKind:
        project = self.resolve_project(root)
        if (project/"package.json").exists():
            return ProjectKind.NODE
        if (project/"pyproject.toml").exists() or (project/"requirements.txt").exists():
            return ProjectKind.PYTHON
        if list(project.glob("*.py")):
            return ProjectKind.PYTHON
        if (project/"index.html").exists():
            return ProjectKind.STATIC_WEB
        if list(project.rglob("*.cpp")) or list(project.rglob("*.cc")):
            return ProjectKind.CPP
        if list(project.rglob("*.c")):
            return ProjectKind.C
        if list(project.rglob("*.java")):
            return ProjectKind.JAVA
        return ProjectKind.UNKNOWN

    def inspect(self, root: str | Path | None = None) -> ProjectInfo:
        project = self.resolve_project(root)
        files = self.list_project_files(project)
        kind = self.detect_kind(project)
        entry = ""
        deps: list[str] = []
        tests: list[str] = []
        metadata: dict = {}

        marker = project/".conduit_project.json"
        if marker.exists():
            try:
                metadata = json.loads(marker.read_text(encoding="utf-8"))
                entry = str(metadata.get("entry_point") or "")
            except Exception:
                metadata = {}

        if kind is ProjectKind.PYTHON:
            for candidate in ("main.py","app.py","server.py","run.py"):
                if candidate in files:
                    entry = entry or candidate
                    break
            if not entry:
                py_files = [x for x in files if x.endswith(".py") and not Path(x).name.startswith("test_")]
                entry = py_files[0] if py_files else ""
            for name in ("requirements.txt","pyproject.toml"):
                if name in files:
                    deps.append(name)
            tests = [x for x in files if Path(x).name.startswith("test_") or "/tests/" in f"/{x}/"]
        elif kind is ProjectKind.NODE:
            entry = entry or "package.json"
            deps = ["package.json"]
            if "package-lock.json" in files:
                deps.append("package-lock.json")
            tests = [x for x in files if any(token in x.casefold() for token in (".test.", ".spec.", "/test/", "/tests/"))]
        elif kind is ProjectKind.STATIC_WEB:
            entry = entry or "index.html"
        elif kind in {ProjectKind.C, ProjectKind.CPP, ProjectKind.JAVA}:
            suffix = {ProjectKind.C:".c", ProjectKind.CPP:".cpp", ProjectKind.JAVA:".java"}[kind]
            candidates = [x for x in files if x.endswith(suffix)]
            entry = entry or (candidates[0] if candidates else "")

        return ProjectInfo(
            root=project,
            kind=kind,
            name=project.name,
            files=files,
            entry_point=entry,
            dependency_files=deps,
            test_files=tests,
            metadata=metadata,
        )

    @staticmethod
    def _which(names: Iterable[str]) -> str | None:
        for name in names:
            hit = shutil.which(name)
            if hit:
                return hit
        return None

    @staticmethod
    def _sanitized_env() -> dict[str, str]:
        allowed = ("PATH","SYSTEMROOT","WINDIR","TEMP","TMP","HOME","USERPROFILE","APPDATA","LOCALAPPDATA")
        return {key: os.environ[key] for key in allowed if key in os.environ}

    def _run(self, argv: list[str], *, cwd: Path, timeout: float | None = None) -> DevRunResult:
        started = time.perf_counter()
        timeout = self.timeout_seconds if timeout is None else max(1.0, float(timeout))
        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd),
                env=self._sanitized_env(),
                shell=False,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
            )
            stdout = (proc.stdout or "")[:self.output_limit]
            stderr = (proc.stderr or "")[:self.output_limit]
            success = proc.returncode == 0
            category = self.classify_error(stderr or stdout, proc.returncode)
            return DevRunResult(
                success=success, root=cwd, command=tuple(argv),
                exit_code=proc.returncode, stdout=stdout, stderr=stderr,
                category=DevErrorCategory.NONE if success else category,
                message="Project command completed successfully." if success else "Project command failed.",
                duration_seconds=time.perf_counter()-started,
            )
        except subprocess.TimeoutExpired as exc:
            return DevRunResult(
                False, cwd, tuple(argv), None,
                (exc.stdout or "")[:self.output_limit] if isinstance(exc.stdout, str) else "",
                (exc.stderr or "")[:self.output_limit] if isinstance(exc.stderr, str) else "",
                DevErrorCategory.TIMEOUT,
                f"Project command timed out after {timeout:.0f} seconds.",
                time.perf_counter()-started,
            )
        except PermissionError as exc:
            return DevRunResult(False, cwd, tuple(argv), None, "", str(exc), DevErrorCategory.PERMISSION_ERROR, str(exc))
        except FileNotFoundError as exc:
            return DevRunResult(False, cwd, tuple(argv), None, "", str(exc), DevErrorCategory.BUILD_TOOL_MISSING, str(exc))

    @staticmethod
    def classify_error(text: str, exit_code: int | None = None) -> DevErrorCategory:
        lower = str(text or "").casefold()
        if any(x in lower for x in ("modulenotfounderror","cannot find module","no module named","module not found")):
            return DevErrorCategory.DEPENDENCY_MISSING
        if any(x in lower for x in ("syntaxerror","syntax error","parse error")):
            return DevErrorCategory.SYNTAX_ERROR
        if any(x in lower for x in ("assertionerror","failed tests","test failed"," tests failed")):
            return DevErrorCategory.TEST_FAILURE
        if any(x in lower for x in ("compilation failed","compiler error","undefined reference","error cs")):
            return DevErrorCategory.COMPILATION_ERROR
        return DevErrorCategory.RUNTIME_ERROR if exit_code not in {None, 0} else DevErrorCategory.UNKNOWN

    def _python_entry(self, info: ProjectInfo) -> Path:
        if not info.entry_point:
            raise DeveloperAgentError("I couldn't determine this Python project's entry point.")
        entry = (info.root/self._safe_relpath(info.entry_point)).resolve()
        if not self._inside(info.root, entry) or not entry.exists():
            raise DeveloperAgentError(f"Python entry point does not exist: {info.entry_point}")
        return entry

    def run_project(self, root: str | Path | None = None, *, timeout: float | None = None) -> DevRunResult:
        info = self.inspect(root)
        if info.kind is ProjectKind.PYTHON:
            python = sys.executable
            entry = self._python_entry(info)
            return self._run([python, str(entry.relative_to(info.root))], cwd=info.root, timeout=timeout)

        if info.kind is ProjectKind.NODE:
            npm = self._which(("npm.cmd","npm"))
            if not npm:
                return DevRunResult(False, info.root, category=DevErrorCategory.BUILD_TOOL_MISSING, message="npm is not installed.")
            try:
                package = json.loads((info.root/"package.json").read_text(encoding="utf-8"))
                scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
            except Exception:
                scripts = {}
            script = "start" if "start" in scripts else "dev" if "dev" in scripts else ""
            if not script:
                return DevRunResult(False, info.root, category=DevErrorCategory.ENTRY_POINT_MISSING, message="package.json has no start or dev script.")
            return self._run([npm, "run", script], cwd=info.root, timeout=timeout)

        if info.kind is ProjectKind.STATIC_WEB:
            return DevRunResult(
                True, info.root, message=f"Static web project entry point: {info.root/'index.html'}",
                data={"entry_point": str(info.root/"index.html")},
            )

        return DevRunResult(
            False, info.root, category=DevErrorCategory.BUILD_TOOL_MISSING,
            message=f"Project runner is not configured yet for {info.kind.value} projects.",
        )

    def run_tests(self, root: str | Path | None = None, *, timeout: float | None = None) -> DevRunResult:
        info = self.inspect(root)
        if info.kind is ProjectKind.PYTHON:
            pytest = self._which(("pytest.exe","pytest"))
            if pytest:
                return self._run([pytest, "-q"], cwd=info.root, timeout=timeout)
            # Built-in unittest fallback avoids forcing a dependency.
            return self._run(
                [sys.executable, "-m", "unittest", "discover"],
                cwd=info.root, timeout=timeout,
            )
        if info.kind is ProjectKind.NODE:
            npm = self._which(("npm.cmd","npm"))
            if not npm:
                return DevRunResult(False, info.root, category=DevErrorCategory.BUILD_TOOL_MISSING, message="npm is not installed.")
            try:
                package = json.loads((info.root/"package.json").read_text(encoding="utf-8"))
                scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
            except Exception:
                scripts = {}
            if "test" not in scripts:
                return DevRunResult(False, info.root, category=DevErrorCategory.ENTRY_POINT_MISSING, message="package.json has no test script.")
            return self._run([npm, "test", "--", "--runInBand"], cwd=info.root, timeout=timeout)
        return DevRunResult(False, info.root, category=DevErrorCategory.BUILD_TOOL_MISSING, message="Project tests are not configured for this project type.")

    def dependency_install_command(self, root: str | Path | None = None) -> tuple[list[str], Path]:
        info = self.inspect(root)
        if info.kind is ProjectKind.PYTHON:
            requirements = info.root/"requirements.txt"
            if requirements.exists():
                return [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], info.root
            pyproject = info.root/"pyproject.toml"
            if pyproject.exists():
                return [sys.executable, "-m", "pip", "install", "-e", "."], info.root
            raise DeveloperAgentError("This Python project has no requirements.txt or pyproject.toml.")
        if info.kind is ProjectKind.NODE:
            npm = self._which(("npm.cmd","npm"))
            if not npm:
                raise DeveloperAgentError("npm is not installed.")
            return [npm, "install"], info.root
        raise DeveloperAgentError(f"Dependency installation isn't configured for {info.kind.value} projects.")

    def install_dependencies(self, root: str | Path | None = None, *, timeout: float = 300.0) -> DevRunResult:
        argv, cwd = self.dependency_install_command(root)
        return self._run(argv, cwd=cwd, timeout=timeout)

    def patch_files(self, patches: dict[str, str], root: str | Path | None = None) -> list[Path]:
        project = self.resolve_project(root)
        return self.write_files(project, patches, overwrite=True, backup_existing=True)

    def open_editor(self, root: str | Path | None = None) -> str:
        project = self.resolve_project(root)
        code = self._which(("code.cmd","code"))
        if not code:
            raise DeveloperAgentError("Visual Studio Code CLI ('code') was not found on PATH.")
        subprocess.Popen([code, str(project)], cwd=str(project), shell=False)
        return f"Opened {project.name} in Visual Studio Code."

    def manifest_summary(self, root: str | Path | None = None) -> dict:
        info = self.inspect(root)
        return {
            "root": str(info.root),
            "name": info.name,
            "kind": info.kind.value,
            "entry_point": info.entry_point,
            "files": info.files,
            "dependency_files": info.dependency_files,
            "test_files": info.test_files,
        }


dev_service = DeveloperProjectService()
