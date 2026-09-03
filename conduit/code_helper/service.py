from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Iterable

from conduit.file_processing import file_service
from conduit.file_processing.models import FileKind
from .models import CodeRunResult, ErrorCategory


class CodeHelperError(RuntimeError):
    pass


EXTENSION_LANGUAGE = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".java": "java", ".c": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".cs": "csharp", ".go": "go", ".rs": "rust", ".php": "php",
    ".rb": "ruby", ".kt": "kotlin", ".kts": "kotlin", ".swift": "swift",
    ".html": "html", ".css": "css", ".sql": "sql",
}
LANGUAGE_EXTENSION = {
    "python": ".py", "py": ".py", "javascript": ".js", "js": ".js",
    "typescript": ".ts", "ts": ".ts", "java": ".java", "c": ".c",
    "cpp": ".cpp", "c++": ".cpp", "csharp": ".cs", "c#": ".cs",
    "go": ".go", "rust": ".rs", "php": ".php", "ruby": ".rb",
    "kotlin": ".kt", "swift": ".swift", "html": ".html", "css": ".css",
    "sql": ".sql",
}
RUNNABLE = {"python", "javascript", "java", "c", "cpp"}


class CodeHelperService:
    """Single-file code workspace and restricted runner.

    Execution is deliberately *not* an OS security sandbox. It copies the source
    into a temporary workspace, uses an executable allowlist, shell=False,
    sanitized environment, output limits and timeouts. A future project agent can
    upgrade this runner to a container without changing the code-helper API.
    """

    def __init__(self, *, timeout_seconds: float = 20.0, output_limit: int = 12000) -> None:
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.output_limit = max(1000, int(output_limit))

    @staticmethod
    def detect_language(path: str | Path) -> str:
        return EXTENSION_LANGUAGE.get(Path(path).suffix.casefold(), "unknown")

    def active_code_file(self) -> Path | None:
        item = file_service.get_active_file()
        if item is None or item.kind is not FileKind.CODE:
            return None
        return item.path.resolve()

    def resolve_code_file(self, path: str | Path | None = None) -> Path:
        if path not in {None, ""}:
            candidate = Path(str(path)).expanduser().resolve()
        else:
            active = self.active_code_file()
            if active is None:
                raise CodeHelperError("No active code file is set. Drop a code file into Conduit first.")
            candidate = active
        if not candidate.exists() or not candidate.is_file():
            raise CodeHelperError(f"Code file does not exist: {candidate}")
        if self.detect_language(candidate) == "unknown":
            raise CodeHelperError(f"Unsupported code-file extension: {candidate.suffix or '(none)'}")
        return candidate

    def read(self, path: str | Path | None = None) -> str:
        target = self.resolve_code_file(path)
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return target.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _desktop_dir() -> Path:
        candidates = [Path.home()/"Desktop", Path.home()/"OneDrive"/"Desktop"]
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate.resolve()
        # Useful in tests/non-Windows environments; Windows normally has Desktop.
        fallback = Path.home()/"Desktop"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback.resolve()

    @staticmethod
    def _safe_stem(text: str) -> str:
        words = re.findall(r"[A-Za-z0-9]+", text)
        stop = {"generate","create","write","make","code","file","script","program","a","an","the","in","using","with","for","me","please"}
        useful = [w.casefold() for w in words if w.casefold() not in stop]
        stem = "_".join(useful[:5]).strip("_") or "conduit_code"
        return stem[:60]

    def default_generated_path(self, *, language: str, prompt: str, filename: str = "", base_dir: str | Path | None = None) -> Path:
        ext = LANGUAGE_EXTENSION.get(language.casefold())
        if not ext:
            raise CodeHelperError(f"Unsupported generation language: {language}")
        name = Path(filename).name.strip() if filename else ""
        if name:
            if Path(name).suffix.casefold() != ext:
                name = Path(name).stem + ext
        else:
            name = self._safe_stem(prompt) + ext
        directory = Path(base_dir).expanduser().resolve() if base_dir else self._desktop_dir()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory/name
        if not target.exists():
            return target
        for i in range(2, 1000):
            candidate = target.with_name(f"{target.stem}_{i}{target.suffix}")
            if not candidate.exists():
                return candidate
        raise CodeHelperError("Could not choose a free Desktop filename.")

    def write_generated(self, content: str, *, language: str, prompt: str, filename: str = "", path: str = "", base_dir: str | Path | None = None) -> Path:
        if path:
            target = Path(path).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            target = self.default_generated_path(language=language, prompt=prompt, filename=filename, base_dir=base_dir)
        target.write_text(content.rstrip()+"\n", encoding="utf-8")
        try:
            file_service.set_active_file(target, source="filesystem")
        except Exception:
            pass
        return target

    @staticmethod
    def _backup_path(path: Path) -> Path:
        backup_dir = path.parent/".conduit_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        candidate = backup_dir/f"{path.name}.{stamp}.bak"
        n=2
        while candidate.exists():
            candidate=backup_dir/f"{path.name}.{stamp}-{n}.bak"; n+=1
        return candidate

    def replace(self, content: str, path: str | Path | None = None, *, create_backup: bool = True) -> tuple[Path, Path | None]:
        target = self.resolve_code_file(path)
        backup = None
        if create_backup:
            backup = self._backup_path(target)
            shutil.copy2(target, backup)
        target.write_text(content.rstrip()+"\n", encoding="utf-8")
        return target, backup

    @staticmethod
    def strip_code_fences(text: str) -> str:
        """Remove Markdown code fences even when a model emits an unmatched fence.

        Smaller/local models occasionally obey the source-code request but leave
        only a trailing ``` token. That token must never be written into source.
        """
        value = str(text or "").strip()
        if not value:
            return value
        value = re.sub(r"^```(?:[A-Za-z0-9_+#.-]+)?\s*(?:\r?\n)?", "", value)
        value = re.sub(r"(?:\r?\n)?```\s*$", "", value)
        return value.strip()

    def validate_source(self, content: str, *, language: str) -> tuple[bool, str]:
        source = self.strip_code_fences(content)
        if not source.strip():
            return False, "The model returned empty source code."
        lang = language.casefold().strip()
        try:
            if lang == "python":
                import ast
                ast.parse(source)
                return True, ""
            suffix = LANGUAGE_EXTENSION.get(lang)
            if not suffix:
                return True, ""
            with tempfile.TemporaryDirectory(prefix="conduit-code-check-") as td:
                temp = Path(td)
                file = temp / f"candidate{suffix}"
                file.write_text(source.rstrip() + "\n", encoding="utf-8")
                if lang == "javascript":
                    exe = self._which_any(("node", "node.exe"))
                    if not exe: return True, ""
                    code,out,err,_,timed_out = self._run_process([exe, "--check", file.name], cwd=temp, timeout=10.0)
                    return (False, "JavaScript syntax validation timed out.") if timed_out else (code == 0, (err or out).strip())
                if lang == "java":
                    exe = self._which_any(("javac", "javac.exe"))
                    if not exe: return True, ""
                    code,out,err,_,timed_out = self._run_process([exe, file.name], cwd=temp, timeout=12.0)
                    return (False, "Java compilation validation timed out.") if timed_out else (code == 0, (err or out).strip())
                if lang == "c":
                    exe = self._which_any(("gcc", "clang"))
                    if not exe: return True, ""
                    code,out,err,_,timed_out = self._run_process([exe, "-fsyntax-only", file.name], cwd=temp, timeout=12.0)
                    return (False, "C syntax validation timed out.") if timed_out else (code == 0, (err or out).strip())
                if lang == "cpp":
                    exe = self._which_any(("g++", "clang++"))
                    if not exe: return True, ""
                    code,out,err,_,timed_out = self._run_process([exe, "-fsyntax-only", file.name], cwd=temp, timeout=12.0)
                    return (False, "C++ syntax validation timed out.") if timed_out else (code == 0, (err or out).strip())
        except SyntaxError as exc:
            return False, f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        return True, ""

    @staticmethod
    def classify_error(stderr: str, stdout: str = "") -> ErrorCategory:
        text = f"{stderr}\n{stdout}".casefold()
        if not text.strip(): return ErrorCategory.NONE
        if "timed out" in text: return ErrorCategory.TIMEOUT
        if "modulenotfounderror" in text or "no module named" in text or "cannot find module" in text:
            return ErrorCategory.DEPENDENCY_MISSING
        if "importerror" in text: return ErrorCategory.IMPORT_ERROR
        if "syntaxerror" in text or "indentationerror" in text: return ErrorCategory.SYNTAX_ERROR
        if "typeerror" in text: return ErrorCategory.TYPE_ERROR
        if "assertionerror" in text or "assertion failed" in text: return ErrorCategory.ASSERTION_FAILURE
        if "permission denied" in text or "access is denied" in text: return ErrorCategory.PERMISSION_ERROR
        if "no such file" in text or "filenotfounderror" in text: return ErrorCategory.FILE_NOT_FOUND
        if "not recognized as an internal or external command" in text or "is not recognized" in text:
            return ErrorCategory.RUNTIME_MISSING
        if "error:" in text or "compilation failed" in text: return ErrorCategory.COMPILATION_ERROR
        if "traceback" in text or "exception" in text: return ErrorCategory.RUNTIME_ERROR
        return ErrorCategory.UNKNOWN

    @staticmethod
    def _sanitized_env(temp_dir: Path) -> dict[str, str]:
        allowed = ("PATH","PATHEXT","SYSTEMROOT","WINDIR","COMSPEC","TEMP","TMP","NUMBER_OF_PROCESSORS")
        env = {k:v for k,v in os.environ.items() if k.upper() in allowed}
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["HOME"] = str(temp_dir)
        env["USERPROFILE"] = str(temp_dir)
        env["TEMP"] = str(temp_dir)
        env["TMP"] = str(temp_dir)
        return env

    @staticmethod
    def _which_any(names: Iterable[str]) -> str | None:
        for name in names:
            value = shutil.which(name)
            if value: return value
        return None

    def _run_process(self, command: list[str], *, cwd: Path, timeout: float | None = None) -> tuple[int|None,str,str,float,bool]:
        started=time.monotonic()
        try:
            completed=subprocess.run(
                command, cwd=str(cwd), env=self._sanitized_env(cwd),
                capture_output=True, text=True, errors="replace", shell=False,
                timeout=timeout or self.timeout_seconds, check=False,
            )
            out=(completed.stdout or "")[:self.output_limit]
            err=(completed.stderr or "")[:self.output_limit]
            return completed.returncode,out,err,time.monotonic()-started,False
        except subprocess.TimeoutExpired as exc:
            out=str(exc.stdout or "")[:self.output_limit]
            err=(str(exc.stderr or "")+"\nExecution timed out.")[:self.output_limit]
            return None,out,err,time.monotonic()-started,True

    def run(self, path: str | Path | None = None, *, timeout: float | None = None) -> CodeRunResult:
        source=self.resolve_code_file(path)
        language=self.detect_language(source)
        if language not in RUNNABLE:
            return CodeRunResult(False,language,source,category=ErrorCategory.RUNTIME_MISSING,
                message=f"Single-file execution is not configured for {language} yet. The file can still be explained, reviewed, edited, or optimized.")
        with tempfile.TemporaryDirectory(prefix="conduit-code-") as td:
            sandbox=Path(td)
            local=sandbox/source.name
            shutil.copy2(source,local)
            command:list[str]
            compile_command:list[str]|None=None
            run_command:list[str]|None=None
            if language=="python":
                exe=sys.executable
                command=[exe,"-I","-B",local.name]
            elif language=="javascript":
                exe=self._which_any(("node","node.exe"))
                if not exe:
                    return CodeRunResult(False,language,source,category=ErrorCategory.RUNTIME_MISSING,message="Node.js is not installed or not on PATH.")
                command=[exe,local.name]
            elif language=="java":
                javac=self._which_any(("javac","javac.exe")); java=self._which_any(("java","java.exe"))
                if not javac or not java:
                    return CodeRunResult(False,language,source,category=ErrorCategory.RUNTIME_MISSING,message="Java JDK (javac/java) is not installed or not on PATH.")
                compile_command=[javac,local.name]
                run_command=[java,local.stem]
                command=compile_command
            elif language=="c":
                cc=self._which_any(("gcc","clang"))
                if not cc:
                    return CodeRunResult(False,language,source,category=ErrorCategory.RUNTIME_MISSING,message="A C compiler (gcc/clang) is not installed or not on PATH.")
                exe_name="program.exe" if os.name=="nt" else "program"
                compile_command=[cc,local.name,"-o",exe_name]
                run_command=[str(sandbox/exe_name)]
                command=compile_command
            else: # cpp
                cc=self._which_any(("g++","clang++"))
                if not cc:
                    return CodeRunResult(False,language,source,category=ErrorCategory.RUNTIME_MISSING,message="A C++ compiler (g++/clang++) is not installed or not on PATH.")
                exe_name="program.exe" if os.name=="nt" else "program"
                compile_command=[cc,local.name,"-o",exe_name]
                run_command=[str(sandbox/exe_name)]
                command=compile_command

            if compile_command is not None:
                code,out,err,duration,timed_out=self._run_process(compile_command,cwd=sandbox,timeout=timeout)
                if timed_out or code!=0:
                    category=ErrorCategory.TIMEOUT if timed_out else self.classify_error(err,out)
                    return CodeRunResult(False,language,source,tuple(compile_command),code,out,err,category,
                        "Compilation failed." if not timed_out else "Compilation timed out.",duration)
                command=run_command or []

            code,out,err,duration,timed_out=self._run_process(command,cwd=sandbox,timeout=timeout)
            category=ErrorCategory.TIMEOUT if timed_out else (ErrorCategory.NONE if code==0 else self.classify_error(err,out))
            success=(code==0 and not timed_out)
            message="Code ran successfully." if success else ("Execution timed out." if timed_out else "Code execution failed.")
            return CodeRunResult(success,language,source,tuple(command),code,out,err,category,message,duration)

    def test(self, path: str | Path | None = None, *, timeout: float | None = None) -> CodeRunResult:
        # Single-file scope: syntax/compile + execution is the test. Multi-file
        # test discovery belongs to the later dev project agent.
        return self.run(path, timeout=timeout)

    @staticmethod
    def validate_package_name(package: str) -> str:
        value=package.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", value):
            raise CodeHelperError("Invalid dependency name. Only a plain package name is allowed.")
        return value

    def install_dependency(self, package: str, *, language: str) -> CodeRunResult:
        package=self.validate_package_name(package)
        lang=language.casefold()
        if lang=="python":
            command=[sys.executable,"-m","pip","install",package]
        elif lang=="javascript":
            npm=self._which_any(("npm","npm.cmd"))
            if not npm:
                return CodeRunResult(False,lang,Path.cwd(),category=ErrorCategory.RUNTIME_MISSING,message="npm is not installed or not on PATH.")
            command=[npm,"install","--global",package]
        else:
            return CodeRunResult(False,lang,Path.cwd(),category=ErrorCategory.RUNTIME_MISSING,message=f"Automatic single-file dependency installation is not configured for {lang}.")
        with tempfile.TemporaryDirectory(prefix="conduit-install-") as td:
            code,out,err,duration,timed_out=self._run_process(command,cwd=Path(td),timeout=120.0)
        success=(code==0 and not timed_out)
        category=ErrorCategory.NONE if success else (ErrorCategory.TIMEOUT if timed_out else self.classify_error(err,out))
        return CodeRunResult(success,lang,Path.cwd(),tuple(command),code,out,err,category,
            f"Installed dependency {package}." if success else f"Dependency installation failed for {package}.",duration)


code_service = CodeHelperService()
