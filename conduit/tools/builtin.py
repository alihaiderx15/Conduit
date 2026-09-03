from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Iterable

from conduit.web_intelligence import WebIntelligenceService
from conduit.file_processing import file_service
from conduit.file_processing.common import FileProcessingError, DependencyUnavailable
from conduit.code_helper import code_service, CodeHelperError
from conduit.dev_agent import dev_service, DeveloperAgentError, ProjectPlan
from conduit.games import games_service, GamesError
from conduit.environment import environment_service

from .models import ToolResult, ToolRisk
from .registry import ToolRegistry, tool

registry = ToolRegistry()


def _expanded(path: str) -> Path:
    return Path(os.path.abspath(os.path.expandvars(os.path.expanduser(path))))


@tool(registry, name="open_calculator", description="Open the operating system calculator application.")
def open_calculator() -> ToolResult:
    if sys.platform == "win32":
        subprocess.Popen(["calc.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        return ToolResult(False, "This action currently targets Windows.", error_type="UnsupportedPlatform")
    return ToolResult(True, "Calculator is now open.")


@tool(
    registry,
    name="system.open_url",
    description="Open an HTTP/HTTPS URL visibly using the operating system's configured default browser.",
    parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
)
def open_url(url: str) -> ToolResult:
    value = url.strip()
    if not value.casefold().startswith(("http://", "https://")):
        raise ValueError("url must start with http:// or https://.")
    if sys.platform != "win32":
        return ToolResult(False, "This action currently targets Windows.", error_type="UnsupportedPlatform")
    # Windows shell URL association is the source of truth. This deliberately
    # does not name Chrome/Edge/Opera/Firefox and therefore respects the user's
    # configured default browser.
    os.startfile(value)  # type: ignore[attr-defined]
    return ToolResult(
        True,
        "Opened URL in the Windows default browser.",
        {"url": value, "browser_policy": "windows_default"},
    )


@tool(
    registry,
    name="system.open_path",
    description="Open a local file or folder using its default Windows application.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
)
def open_path(path: str) -> ToolResult:
    target = _expanded(path)
    if not target.exists():
        return ToolResult(False, f"Path does not exist: {target}", error_type="FileNotFoundError")
    if sys.platform != "win32":
        return ToolResult(False, "This action currently targets Windows.", error_type="UnsupportedPlatform")
    os.startfile(str(target))  # type: ignore[attr-defined]
    return ToolResult(True, f"Opened {target}.", {"path": str(target)})


@tool(
    registry,
    name="system.list_processes",
    description="List currently running process image names on Windows.",
)
def list_processes() -> ToolResult:
    if sys.platform != "win32":
        return ToolResult(False, "This action currently targets Windows.", error_type="UnsupportedPlatform")
    completed = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False)
    names: list[str] = []
    for line in completed.stdout.splitlines():
        if line.startswith('"'):
            names.append(line.split('","', 1)[0].strip('"'))
    unique = sorted(set(names), key=str.casefold)
    return ToolResult(True, f"Found {len(unique)} running process types.", {"processes": unique[:250]})


@tool(
    registry,
    name="system.wait",
    description="Wait briefly for an application or dialog to become ready.",
    parameters={"type": "object", "properties": {"seconds": {"type": "number", "minimum": 0.1, "maximum": 10}}, "required": ["seconds"]},
)
def wait(seconds: float) -> ToolResult:
    duration = max(0.1, min(float(seconds), 10.0))
    time.sleep(duration)
    return ToolResult(True, f"Waited {duration:.1f} second(s).", {"seconds": duration})


@tool(
    registry,
    name="create_folder",
    description="Create a new folder at the requested path.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    risk=ToolRisk.CONFIRM,
)
def create_folder(path: str) -> ToolResult:
    target = _expanded(path)
    target.mkdir(parents=True, exist_ok=False)
    return ToolResult(True, f"Created folder: {target}", {"path": str(target)})


@tool(
    registry,
    name="files.exists",
    description="Check whether a local file or folder exists.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
)
def file_exists(path: str) -> ToolResult:
    target = _expanded(path)
    return ToolResult(True, f"Existence checked for {target}.", {"path": str(target), "exists": target.exists(), "is_file": target.is_file(), "is_dir": target.is_dir()})


@tool(
    registry,
    name="files.list_directory",
    description="List files and folders directly inside a local directory.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}, "required": ["path"]},
)
def list_directory(path: str, limit: int = 100) -> ToolResult:
    target = _expanded(path)
    if not target.is_dir():
        return ToolResult(False, f"Directory does not exist: {target}", error_type="NotADirectoryError")
    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))[:limit]:
        entries.append({"name": item.name, "path": str(item), "type": "directory" if item.is_dir() else "file", "size": item.stat().st_size if item.is_file() else None})
    return ToolResult(True, f"Listed {len(entries)} item(s) in {target}.", {"path": str(target), "entries": entries})


@tool(
    registry,
    name="files.search",
    description="Search recursively for local files or folders whose names contain a query.",
    parameters={"type": "object", "properties": {"root": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "required": ["root", "query"]},
)
def search_files(root: str, query: str, limit: int = 50) -> ToolResult:
    base = _expanded(root)
    if not base.is_dir():
        return ToolResult(False, f"Search root does not exist: {base}", error_type="NotADirectoryError")
    needle = query.casefold().strip()
    matches: list[dict[str, str]] = []
    for current, dirs, files in os.walk(base):
        for name in [*dirs, *files]:
            if needle in name.casefold():
                path = Path(current) / name
                matches.append({"name": name, "path": str(path), "type": "directory" if path.is_dir() else "file"})
                if len(matches) >= limit:
                    return ToolResult(True, f"Found {len(matches)} matching item(s).", {"matches": matches})
    return ToolResult(True, f"Found {len(matches)} matching item(s).", {"matches": matches})


@tool(
    registry,
    name="files.read_text",
    description="Read a UTF-8 text file with a size limit.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}, "max_chars": {"type": "integer", "minimum": 1, "maximum": 200000}}, "required": ["path"]},
)
def read_text(path: str, max_chars: int = 50000) -> ToolResult:
    target = _expanded(path)
    if not target.is_file():
        return ToolResult(False, f"File does not exist: {target}", error_type="FileNotFoundError")
    text = target.read_text(encoding="utf-8", errors="replace")
    truncated = len(text) > max_chars
    return ToolResult(
        True,
        f"Read {target.name}.",
        {
            "path": str(target),
            "text": text[:max_chars],
            "content": text[:max_chars],
            "truncated": truncated,
        },
    )


@tool(
    registry,
    name="files.write_text",
    description="Create or overwrite a UTF-8 text file.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}, "text": {"type": "string"}}, "required": ["path", "text"]},
    risk=ToolRisk.CONFIRM,
)
def write_text(path: str, text: str) -> ToolResult:
    target = _expanded(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return ToolResult(True, f"Wrote text to {target}.", {"path": str(target), "characters": len(text)})


@tool(
    registry,
    name="files.copy",
    description="Copy a local file or directory to a new path.",
    parameters={"type": "object", "properties": {"source": {"type": "string"}, "destination": {"type": "string"}}, "required": ["source", "destination"]},
    risk=ToolRisk.CONFIRM,
)
def copy_path(source: str, destination: str) -> ToolResult:
    src, dst = _expanded(source), _expanded(destination)
    if not src.exists():
        return ToolResult(False, f"Source does not exist: {src}", error_type="FileNotFoundError")
    if src.is_dir(): shutil.copytree(src, dst)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)
    return ToolResult(True, f"Copied {src} to {dst}.", {"source": str(src), "destination": str(dst)})


@tool(
    registry,
    name="files.move",
    description="Move or rename a local file or directory.",
    parameters={"type": "object", "properties": {"source": {"type": "string"}, "destination": {"type": "string"}}, "required": ["source", "destination"]},
    risk=ToolRisk.CONFIRM,
)
def move_path(source: str, destination: str) -> ToolResult:
    src, dst = _expanded(source), _expanded(destination)
    if not src.exists():
        return ToolResult(False, f"Source does not exist: {src}", error_type="FileNotFoundError")
    dst.parent.mkdir(parents=True, exist_ok=True)
    result = shutil.move(str(src), str(dst))
    return ToolResult(True, f"Moved {src} to {result}.", {"source": str(src), "destination": str(result)})

@tool(
    registry,
    name="files.info",
    description="Read metadata for a local file or folder without modifying it.",
    parameters={"type":"object","properties":{"path":{"type":"string"}},"required":["path"]},
)
def file_info(path: str) -> ToolResult:
    target = _expanded(path)
    if not target.exists():
        return ToolResult(False, f"Path does not exist: {target}", error_type="FileNotFoundError")
    stat = target.stat()
    return ToolResult(True, f"Read metadata for {target.name}.", {
        "path": str(target), "name": target.name, "is_file": target.is_file(),
        "is_dir": target.is_dir(), "size": stat.st_size, "modified": stat.st_mtime,
    })


@tool(
    registry,
    name="files.append_text",
    description="Append UTF-8 text to an existing or new text file.",
    parameters={"type":"object","properties":{"path":{"type":"string"},"text":{"type":"string"}},"required":["path","text"]},
    risk=ToolRisk.CONFIRM,
)
def append_text(path: str, text: str) -> ToolResult:
    target = _expanded(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(text)
    return ToolResult(True, f"Appended text to {target}.", {"path": str(target), "characters": len(text)})


@tool(registry, name="clipboard.read", description="Read plain text currently stored in the Windows clipboard.")
def clipboard_read() -> ToolResult:
    if sys.platform != "win32":
        return ToolResult(False, "This action currently targets Windows.", error_type="UnsupportedPlatform")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        return ToolResult(False, completed.stderr.strip() or "Unable to read clipboard.", error_type="ClipboardError")
    return ToolResult(True, "Read clipboard text.", {"text": completed.stdout})


@tool(
    registry, name="clipboard.write", description="Replace the Windows clipboard with plain text.",
    parameters={"type":"object","properties":{"text":{"type":"string"}},"required":["text"]},
    risk=ToolRisk.CONFIRM,
)
def clipboard_write(text: str) -> ToolResult:
    if sys.platform != "win32":
        return ToolResult(False, "This action currently targets Windows.", error_type="UnsupportedPlatform")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "Set-Clipboard -Value $input"],
        input=text, capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        return ToolResult(False, completed.stderr.strip() or "Unable to write clipboard.", error_type="ClipboardError")
    return ToolResult(True, "Updated clipboard text.", {"characters": len(text)})


def _window_api():
    if sys.platform != "win32":
        return None
    import ctypes
    return ctypes.windll.user32


@tool(registry, name="system.active_window", description="Read the title of the current foreground Windows window.")
def active_window() -> ToolResult:
    user32 = _window_api()
    if user32 is None:
        return ToolResult(False, "This action currently targets Windows.", error_type="UnsupportedPlatform")
    import ctypes
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return ToolResult(True, "Read the active window.", {"title": buf.value, "handle": int(hwnd)})


@tool(registry, name="system.list_windows", description="List visible top-level Windows application windows and their titles.")
def list_windows() -> ToolResult:
    user32 = _window_api()
    if user32 is None:
        return ToolResult(False, "This action currently targets Windows.", error_type="UnsupportedPlatform")
    import ctypes
    windows = []
    CALLBACK = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value.strip():
                windows.append({"handle": int(hwnd), "title": buf.value})
        return True
    user32.EnumWindows(CALLBACK(callback), 0)
    return ToolResult(True, f"Found {len(windows)} visible window(s).", {"windows": windows[:100]})


def _find_window_by_title(query: str):
    result = list_windows()
    if not result.success:
        return None
    needle = query.casefold()
    for item in result.data.get("windows", []):
        if needle in item["title"].casefold():
            return int(item["handle"]), item["title"]
    return None


@tool(
    registry,
    name="system.activate_window",
    description="Bring a visible Windows window to the foreground using either a title query or a window handle.",
    parameters={
        "type":"object",
        "properties":{"title":{"type":"string"},"handle":{"type":"integer"}},
    },
)
def activate_window(title: str | None = None, handle: int | None = None) -> ToolResult:
    actual = ""
    if handle is not None:
        hwnd = int(handle)
        for item in list_windows().data.get("windows", []):
            if int(item["handle"]) == hwnd:
                actual = str(item["title"])
                break
        if not actual:
            return ToolResult(False, f"No visible window has handle {hwnd}.", error_type="WindowNotFoundError")
    elif title:
        found = _find_window_by_title(title)
        if not found:
            return ToolResult(False, f"No visible window title contained {title!r}.", error_type="WindowNotFoundError")
        hwnd, actual = found
    else:
        return ToolResult(False, "Provide either title or handle.", error_type="ToolValidationError")

    user32 = _window_api()
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    return ToolResult(True, f"Activated {actual}.", {"title": actual, "handle": hwnd})


@tool(
    registry,
    name="system.window_state",
    description="Minimize, maximize, or restore a visible Windows window using either a title query or a window handle.",
    parameters={
        "type":"object",
        "properties":{
            "title":{"type":"string"},
            "handle":{"type":"integer"},
            "state":{"type":"string","enum":["minimize","maximize","restore"]},
        },
        "required":["state"],
    },
)
def window_state(
    state: str,
    title: str | None = None,
    handle: int | None = None,
) -> ToolResult:
    actual = ""
    if handle is not None:
        hwnd = int(handle)
        for item in list_windows().data.get("windows", []):
            if int(item["handle"]) == hwnd:
                actual = str(item["title"])
                break
        if not actual:
            return ToolResult(False, f"No visible window has handle {hwnd}.", error_type="WindowNotFoundError")
    elif title:
        found = _find_window_by_title(title)
        if not found:
            return ToolResult(False, f"No visible window title contained {title!r}.", error_type="WindowNotFoundError")
        hwnd, actual = found
    else:
        return ToolResult(False, "Provide either title or handle.", error_type="ToolValidationError")

    codes = {"minimize": 6, "maximize": 3, "restore": 9}
    user32 = _window_api()
    user32.ShowWindow(hwnd, codes[state])
    return ToolResult(True, f"Set {actual} to {state}.", {"title": actual, "state": state, "handle": hwnd})


@tool(
    registry, name="files.delete",
    description="Delete a local file or directory. This is destructive and always requires approval.",
    parameters={"type":"object","properties":{"path":{"type":"string"},"recursive":{"type":"boolean"}},"required":["path"]},
    risk=ToolRisk.CONFIRM,
)
def delete_path(path: str, recursive: bool = False) -> ToolResult:
    target=_expanded(path)
    if not target.exists():
        return ToolResult(False,f"Path does not exist: {target}",error_type="FileNotFoundError")
    if target.is_dir():
        if recursive: shutil.rmtree(target)
        else:
            try: target.rmdir()
            except OSError:
                return ToolResult(False,f"Directory is not empty: {target}. Recursive deletion was not approved.",error_type="DirectoryNotEmptyError")
    else: target.unlink()
    return ToolResult(True,f"Deleted {target}.",{"path":str(target),"recursive":bool(recursive)})


@tool(
    registry, name="files.list_recent",
    description="List the most recently modified files inside a directory, optionally recursively.",
    parameters={"type":"object","properties":{"path":{"type":"string"},"recursive":{"type":"boolean"},"limit":{"type":"integer","minimum":1,"maximum":100}},"required":["path"]},
)
def list_recent_files(path: str, recursive: bool=False, limit: int=20) -> ToolResult:
    base=_expanded(path)
    if not base.is_dir():
        return ToolResult(False,f"Directory does not exist: {base}",error_type="NotADirectoryError")
    iterator=base.rglob("*") if recursive else base.iterdir()
    items=[]
    for item in iterator:
        if item.is_file():
            try: stat=item.stat()
            except OSError: continue
            items.append({"name":item.name,"path":str(item),"size":stat.st_size,"modified":stat.st_mtime})
    items.sort(key=lambda item:item["modified"],reverse=True)
    items=items[:limit]
    return ToolResult(True,f"Found {len(items)} recent file(s) in {base}.",{"path":str(base),"files":items})


@tool(
    registry, name="system.process_info",
    description="Check whether a Windows process is running and return matching process details.",
    parameters={"type":"object","properties":{"process":{"type":"string"}},"required":["process"]},
)
def process_info(process: str) -> ToolResult:
    if sys.platform!="win32":
        return ToolResult(False,"This action currently targets Windows.",error_type="UnsupportedPlatform")
    import csv
    needle=process.strip().casefold()
    if needle and not needle.endswith(".exe"): needle += ".exe"
    completed=subprocess.run(["tasklist","/FO","CSV","/NH"],capture_output=True,text=True,check=False)
    matches=[]
    for row in csv.reader(completed.stdout.splitlines()):
        if len(row)>=5 and row[0].casefold()==needle:
            matches.append({"image_name":row[0],"pid":int(row[1]) if row[1].isdigit() else row[1],"session_name":row[2],"memory":row[4]})
    return ToolResult(True,f"Found {len(matches)} running instance(s) of {needle}.",{"process":needle,"running":bool(matches),"instances":matches})


@tool(
    registry, name="system.window_bounds",
    description="Read the screen position and size of a visible Windows window by title or handle.",
    parameters={"type":"object","properties":{"title":{"type":"string"},"handle":{"type":"integer"}}},
)
def window_bounds(title: str|None=None, handle: int|None=None) -> ToolResult:
    user32=_window_api()
    if user32 is None:
        return ToolResult(False,"This action currently targets Windows.",error_type="UnsupportedPlatform")
    import ctypes
    from ctypes import wintypes
    actual=""; hwnd=0
    if handle is not None:
        hwnd=int(handle)
        for item in list_windows().data.get("windows",[]):
            if int(item["handle"])==hwnd: actual=str(item["title"]); break
    elif title:
        found=_find_window_by_title(title)
        if found: hwnd,actual=found
    if not hwnd:
        return ToolResult(False,"No matching visible window was found.",error_type="WindowNotFoundError")
    rect=wintypes.RECT()
    if not user32.GetWindowRect(hwnd,ctypes.byref(rect)):
        return ToolResult(False,"Unable to read window bounds.",error_type="WindowApiError")
    return ToolResult(True,f"Read bounds for {actual}.",{"title":actual,"handle":int(hwnd),"x":rect.left,"y":rect.top,"width":rect.right-rect.left,"height":rect.bottom-rect.top})


@tool(
    registry, name="system.move_resize_window",
    description="Move and resize a visible Windows window by title or handle.",
    parameters={"type":"object","properties":{"title":{"type":"string"},"handle":{"type":"integer"},"x":{"type":"integer"},"y":{"type":"integer"},"width":{"type":"integer","minimum":100},"height":{"type":"integer","minimum":100}},"required":["x","y","width","height"]},
)
def move_resize_window(x:int,y:int,width:int,height:int,title:str|None=None,handle:int|None=None) -> ToolResult:
    user32=_window_api()
    if user32 is None:
        return ToolResult(False,"This action currently targets Windows.",error_type="UnsupportedPlatform")
    actual=""; hwnd=0
    if handle is not None:
        hwnd=int(handle)
        for item in list_windows().data.get("windows",[]):
            if int(item["handle"])==hwnd: actual=str(item["title"]); break
    elif title:
        found=_find_window_by_title(title)
        if found: hwnd,actual=found
    if not hwnd:
        return ToolResult(False,"No matching visible window was found.",error_type="WindowNotFoundError")
    if not user32.MoveWindow(hwnd,int(x),int(y),int(width),int(height),True):
        return ToolResult(False,"Unable to move/resize the window.",error_type="WindowApiError")
    return ToolResult(True,f"Moved/resized {actual}.",{"title":actual,"handle":int(hwnd),"x":int(x),"y":int(y),"width":int(width),"height":int(height)})


async def _web_service_call(method: str, **kwargs) -> ToolResult:
    service = WebIntelligenceService(
        gemini_model=os.getenv("CONDUIT_GEMINI_SEARCH_MODEL", "gemini-flash-latest")
    )
    try:
        response = await getattr(service, method)(**kwargs)
        data = response.to_dict()
        count = len(data.get("results", []))
        message = (
            f"Completed {response.mode} for {response.query!r} "
            f"using {response.provider} with {count} source result(s)."
        )
        return ToolResult(True, message, data)
    except Exception as exc:
        return ToolResult(
            False,
            f"Web intelligence request failed: {exc}",
            error_type=type(exc).__name__,
        )
    finally:
        await service.close()


@tool(
    registry,
    name="web.search",
    description=(
        "Search the live web and return structured titles, URLs, snippets, providers, "
        "and sources. Uses Gemini Google Search grounding when configured and falls "
        "back to DuckDuckGo without an API key."
    ),
    parameters={
        "type":"object",
        "properties":{
            "query":{"type":"string"},
            "limit":{"type":"integer","minimum":1,"maximum":20},
            "use_grounding":{"type":"boolean"},
            "region":{"type":"string"},
            "query_variants":{"type":"array","items":{"type":"string"}},
            "exclude_terms":{"type":"array","items":{"type":"string"}},
        },
        "required":["query"],
    },
)
async def web_search(
    query: str,
    limit: int = 8,
    use_grounding: bool = True,
    region: str = "wt-wt",
    query_variants: list[str] | None = None,
    exclude_terms: list[str] | None = None,
) -> ToolResult:
    return await _web_service_call(
        "search",
        query=query,
        limit=limit,
        use_grounding=use_grounding,
        region=region,
        query_variants=query_variants or (),
        exclude_terms=exclude_terms or (),
    )


@tool(
    registry,
    name="web.news",
    description=(
        "Search current news through several related queries in parallel and return "
        "deduplicated headlines, publishers, dates, URLs, and snippets."
    ),
    parameters={
        "type":"object",
        "properties":{
            "query":{"type":"string"},
            "limit":{"type":"integer","minimum":1,"maximum":30},
            "parallel_queries":{"type":"integer","minimum":1,"maximum":5},
            "query_variants":{"type":"array","items":{"type":"string"}},
            "exclude_terms":{"type":"array","items":{"type":"string"}},
        },
        "required":["query"],
    },
)
async def web_news(
    query: str,
    limit: int = 12,
    parallel_queries: int = 3,
    query_variants: list[str] | None = None,
    exclude_terms: list[str] | None = None,
) -> ToolResult:
    return await _web_service_call(
        "news",
        query=query,
        limit=limit,
        parallel_queries=parallel_queries,
        query_variants=query_variants or (),
        exclude_terms=exclude_terms or (),
    )


@tool(
    registry,
    name="web.research",
    description=(
        "Perform multi-query live research, collect several independent sources, "
        "fetch useful page evidence, and return a source-grounded research bundle. "
        "Uses Gemini Google Search grounding when available."
    ),
    parameters={
        "type":"object",
        "properties":{
            "query":{"type":"string"},
            "depth":{"type":"integer","minimum":1,"maximum":3},
            "sources_per_query":{"type":"integer","minimum":2,"maximum":10},
            "use_grounding":{"type":"boolean"},
            "query_variants":{"type":"array","items":{"type":"string"}},
            "exclude_terms":{"type":"array","items":{"type":"string"}},
            "source_preferences":{"type":"array","items":{"type":"string"}},
        },
        "required":["query"],
    },
)
async def web_research(
    query: str,
    depth: int = 2,
    sources_per_query: int = 5,
    use_grounding: bool = True,
    query_variants: list[str] | None = None,
    exclude_terms: list[str] | None = None,
    source_preferences: list[str] | None = None,
) -> ToolResult:
    return await _web_service_call(
        "research",
        query=query,
        depth=depth,
        sources_per_query=sources_per_query,
        use_grounding=use_grounding,
        query_variants=query_variants or (),
        exclude_terms=exclude_terms or (),
        source_preferences=source_preferences or (),
    )


@tool(
    registry,
    name="web.price_search",
    description=(
        "Search current public product listings for an item and extract visible price "
        "strings with source URLs. Prices are observations, not purchase guarantees."
    ),
    parameters={
        "type":"object",
        "properties":{
            "item":{"type":"string"},
            "region":{"type":"string"},
            "currency":{"type":"string"},
            "limit":{"type":"integer","minimum":1,"maximum":20},
            "query_variants":{"type":"array","items":{"type":"string"}},
            "exclude_terms":{"type":"array","items":{"type":"string"}},
        },
        "required":["item"],
    },
)
async def web_price_search(
    item: str,
    region: str = "",
    currency: str = "",
    limit: int = 10,
    query_variants: list[str] | None = None,
    exclude_terms: list[str] | None = None,
) -> ToolResult:
    return await _web_service_call(
        "price_search",
        item=item,
        region=region,
        currency=currency,
        limit=limit,
        query_variants=query_variants or (),
        exclude_terms=exclude_terms or (),
    )


@tool(
    registry,
    name="web.compare",
    description=(
        "Compare two to six items using parallel live searches, optional price evidence, "
        "and user-specified criteria. Returns evidence for each item and source links."
    ),
    parameters={
        "type":"object",
        "properties":{
            "items":{"type":"array","items":{"type":"string"},"minItems":2,"maxItems":6},
            "criteria":{"type":"array","items":{"type":"string"}},
            "region":{"type":"string"},
            "include_prices":{"type":"boolean"},
        },
        "required":["items"],
    },
)
async def web_compare(
    items: list[str],
    criteria: list[str] | None = None,
    region: str = "",
    include_prices: bool = True,
) -> ToolResult:
    return await _web_service_call(
        "compare",
        items=items,
        criteria=criteria or (),
        region=region,
        include_prices=include_prices,
    )


# ---------------------------------------------------------------------------
# Structured YouTube pack v2.0.16
# ---------------------------------------------------------------------------

@tool(
    registry,
    name="youtube.search",
    description="Search YouTube in the background and return structured video results without opening a visible browser.",
    parameters={"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":20}},"required":["query"]},
)
def youtube_search(query: str, limit: int = 5) -> ToolResult:
    from conduit.capabilities.youtube_structured import search
    videos = search(query, limit=limit)
    return ToolResult(True, f"Found {len(videos)} YouTube video(s).", {"query": query, "videos": [v.data() for v in videos]})


@tool(
    registry,
    name="youtube.play",
    description="Find a YouTube video from a URL, id, or natural-language query and play it visibly in the user's Windows default browser.",
    parameters={"type":"object","properties":{"video":{"type":"string"}},"required":["video"]},
)
def youtube_play(video: str) -> ToolResult:
    from conduit.capabilities.youtube_structured import open_visible
    item = open_visible(video)
    return ToolResult(True, f"Opened {item.title} in the Windows default browser.", {**item.data(), "browser_policy":"windows_default"})


@tool(
    registry,
    name="youtube.get_info",
    description="Retrieve structured metadata for a YouTube video in the background without opening a visible browser.",
    parameters={"type":"object","properties":{"video":{"type":"string"}},"required":["video"]},
)
def youtube_get_info(video: str) -> ToolResult:
    from conduit.capabilities.youtube_structured import get_info
    item = get_info(video)
    return ToolResult(True, f"Retrieved information for {item.title}.", item.data())


@tool(
    registry,
    name="youtube.get_transcript",
    description="Retrieve the transcript of a YouTube video in the background for reading, quoting briefly, or analysis.",
    parameters={"type":"object","properties":{"video":{"type":"string"},"languages":{"type":"array","items":{"type":"string"}}},"required":["video"]},
)
def youtube_get_transcript(video: str, languages: list[str] | None = None) -> ToolResult:
    from conduit.capabilities.youtube_structured import get_transcript
    data = get_transcript(video, languages=languages)
    return ToolResult(True, f"Retrieved the transcript for {data['video']['title']}.", data)


@tool(
    registry,
    name="youtube.summarize",
    description="Retrieve a YouTube video's transcript as structured evidence so Conduit's AI can summarize it conversationally. Does not open a visible browser.",
    parameters={"type":"object","properties":{"video":{"type":"string"},"languages":{"type":"array","items":{"type":"string"}}},"required":["video"]},
)
def youtube_summarize(video: str, languages: list[str] | None = None) -> ToolResult:
    from conduit.capabilities.youtube_structured import get_transcript
    data = get_transcript(video, languages=languages)
    # The dynamic AI loop receives this observation and performs the actual
    # semantic summarization; keeping retrieval separate makes it provider-neutral.
    return ToolResult(True, f"Transcript evidence is ready for summarizing {data['video']['title']}.", data)


@tool(
    registry,
    name="youtube.trending",
    description="Retrieve structured currently trending YouTube videos for a region in the background without opening a visible browser.",
    parameters={"type":"object","properties":{"region":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":25}}},
)
def youtube_trending(region: str = "US", limit: int = 10) -> ToolResult:
    from conduit.capabilities.youtube_structured import trending
    videos = trending(region=region, limit=limit)
    return ToolResult(True, f"Retrieved {len(videos)} trending YouTube video(s) for {region.upper()}.", {"region":region.upper(),"videos":[v.data() for v in videos]})


@tool(
    registry,
    name="youtube.pause",
    description="Pause Conduit's current visible YouTube playback through the Windows media session.",
)
def youtube_pause() -> ToolResult:
    from conduit.capabilities.youtube_structured import pause
    state = pause()
    return ToolResult(True, "Paused YouTube playback.", {"playback_state":state})


@tool(
    registry,
    name="youtube.resume",
    description="Resume Conduit's current visible YouTube playback through the Windows media session.",
)
def youtube_resume() -> ToolResult:
    from conduit.capabilities.youtube_structured import resume
    state = resume()
    return ToolResult(True, "Resumed YouTube playback.", {"playback_state":state})


@tool(
    registry,
    name="youtube.play_latest_upload",
    description="Resolve a YouTube channel's latest standard upload in the background and play it visibly in the user's Windows default browser.",
    parameters={"type":"object","properties":{"channel":{"type":"string"}},"required":["channel"]},
)
def youtube_play_latest_upload(channel: str) -> ToolResult:
    from conduit.capabilities.youtube_structured import play_latest_upload_visible
    item = play_latest_upload_visible(channel)
    return ToolResult(
        True,
        f"Opened the latest upload from {channel} in the Windows default browser.",
        {**item.data(), "channel_query": channel, "browser_policy": "windows_default"},
    )


@tool(
    registry,
    name="youtube.play_oldest_upload",
    description="Resolve a YouTube channel and play its oldest retrievable normal upload visibly in the user's Windows default browser.",
    parameters={"type":"object","properties":{"channel":{"type":"string"}},"required":["channel"]},
)
def youtube_play_oldest_upload(channel: str) -> ToolResult:
    from conduit.capabilities.youtube_structured import play_oldest_upload_visible
    item = play_oldest_upload_visible(channel)
    return ToolResult(True, f"Opened the oldest upload from {channel} in the Windows default browser.", {**item.data(), "channel_query":channel, "browser_policy":"windows_default"})


@tool(
    registry,
    name="youtube.play_most_popular",
    description="Resolve a YouTube channel, verify view counts, and play its most-viewed normal upload in the user's Windows default browser.",
    parameters={"type":"object","properties":{"channel":{"type":"string"}},"required":["channel"]},
)
def youtube_play_most_popular(channel: str) -> ToolResult:
    from conduit.capabilities.youtube_structured import play_most_popular_visible
    item = play_most_popular_visible(channel)
    return ToolResult(True, f"Opened the most popular upload from {channel} in the Windows default browser.", {**item.data(), "channel_query":channel, "browser_policy":"windows_default"})


@tool(
    registry,
    name="youtube.play_live",
    description="Resolve the exact YouTube channel, verify it is currently live, and play that current live stream in the user's Windows default browser. Never substitutes an old stream or another channel.",
    parameters={"type":"object","properties":{"channel":{"type":"string"}},"required":["channel"]},
)
def youtube_play_live(channel: str) -> ToolResult:
    from conduit.capabilities.youtube_structured import play_live_visible
    item = play_live_visible(channel)
    return ToolResult(True, f"Opened the current live stream from {channel} in the Windows default browser.", {**item.data(), "channel_query":channel, "browser_policy":"windows_default"})


@tool(
    registry,
    name="youtube.play_latest_matching",
    description="Search YouTube for a topic/episode, compare relevant candidates by actual upload recency, and play the newest relevant video in the Windows default browser. If channel is supplied, ONLY that exact resolved channel is considered.",
    parameters={
        "type":"object",
        "properties":{
            "query":{"type":"string"},
            "channel":{"type":"string"}
        },
        "required":["query"]
    },
)
def youtube_play_latest_matching(query: str, channel: str = "") -> ToolResult:
    from conduit.capabilities.youtube_structured import play_latest_matching_visible
    item = play_latest_matching_visible(query, channel=channel)
    scope = f" from {channel}" if channel else ""
    return ToolResult(
        True,
        f"Opened the newest relevant YouTube result for {query}{scope} in the Windows default browser.",
        {
            **item.data(),
            "query": query,
            "channel_query": channel,
            "browser_policy": "windows_default",
        },
    )


@tool(
    registry,
    name="youtube.play_matching_video",
    description="Find a vaguely remembered YouTube video from a natural-language description and play the best YouTube-ranked match in the user's Windows default browser. Conversation mode may AI-rerank several candidates before playback.",
    parameters={
        "type":"object",
        "properties":{
            "description":{"type":"string"},
            "search_query":{"type":"string"},
            "channel":{"type":"string"}
        },
        "required":["description"]
    },
)
def youtube_play_matching_video(
    description: str,
    search_query: str = "",
    channel: str = "",
) -> ToolResult:
    from conduit.capabilities.youtube_structured import play_matching_visible
    item = play_matching_visible(
        description,
        search_query=search_query,
        channel=channel,
    )
    return ToolResult(
        True,
        f"Opened the best matching YouTube video, {item.title}, in the Windows default browser.",
        {
            **item.data(),
            "description": description,
            "search_query": search_query,
            "channel_query": channel,
            "browser_policy": "windows_default",
        },
    )


@tool(
    registry,
    name="messaging.resolve_contact",
    description="Structured messaging capability marker: resolve a contact in the user's visible logged-in messaging client. Conversation mode performs the actual vision-guided workflow.",
    parameters={"type":"object","properties":{"service":{"type":"string"},"recipient":{"type":"string"}},"required":["service","recipient"]},
)
def messaging_resolve_contact(service: str, recipient: str) -> ToolResult:
    return ToolResult(True, "Messaging contact resolution is available through conversation mode.", {"service":service,"recipient":recipient,"workflow":"conversation_visible_ui"})


@tool(
    registry,
    name="messaging.open_chat",
    description="Structured messaging capability marker: open a recipient chat in the user's visible messaging client.",
    parameters={"type":"object","properties":{"service":{"type":"string"},"recipient":{"type":"string"}},"required":["service","recipient"]},
)
def messaging_open_chat(service: str, recipient: str) -> ToolResult:
    return ToolResult(True, "Messaging chat opening is available through conversation mode.", {"service":service,"recipient":recipient,"workflow":"conversation_visible_ui"})


@tool(
    registry,
    name="messaging.read_recent",
    description="Structured messaging capability marker: read recent visibly available messages from a requested chat.",
    parameters={"type":"object","properties":{"service":{"type":"string"},"recipient":{"type":"string"},"count":{"type":"integer","minimum":1,"maximum":20}},"required":["service","recipient"]},
)
def messaging_read_recent(service: str, recipient: str, count: int = 5) -> ToolResult:
    return ToolResult(True, "Messaging recent-message reading is available through conversation mode.", {"service":service,"recipient":recipient,"count":count,"workflow":"conversation_visible_ui"})


@tool(
    registry,
    name="messaging.send",
    description="Final external messaging send boundary. Conversation mode must resolve recipient, prepare exact text, and obtain explicit user confirmation before committing the send.",
    parameters={"type":"object","properties":{"service":{"type":"string"},"recipient":{"type":"string"},"message":{"type":"string"}},"required":["service","recipient","message"]},
    risk=ToolRisk.CONFIRM,
)
def messaging_send(service: str, recipient: str, message: str) -> ToolResult:
    return ToolResult(False, "Use the conversation messaging workflow so recipient/text can be verified immediately before sending.", {"service":service,"recipient":recipient}, error_type="MessagingWorkflowRequired")

# ---------------------------------------------------------------------------
# Structured Windows system settings and installed-application control
# ---------------------------------------------------------------------------
from conduit.system_control import windows as _system_windows


@tool(
    registry,
    name="system.apps_installed",
    description="List launchable applications discovered from Windows Start apps, Start Menu shortcuts, desktop shortcuts, and executable paths.",
)
def system_apps_installed() -> ToolResult:
    apps = _system_windows.installed_apps()
    return ToolResult(True, f"Found {len(apps)} launchable apps.", {"apps": apps[:500]})


@tool(
    registry,
    name="system.app_status",
    description="Check whether an application is currently running on Windows.",
    parameters={"type":"object","properties":{"app":{"type":"string"}},"required":["app"]},
)
def system_app_status(app: str) -> ToolResult:
    matches = _system_windows.find_running_app(app)
    return ToolResult(True, f"{app} is {'open' if matches else 'not open'}.", {
        "app": app, "running": bool(matches),
        "processes": [{"pid": x.get("Id"), "name": x.get("ProcessName"), "title": x.get("MainWindowTitle")} for x in matches],
    })


@tool(
    registry,
    name="system.open_app",
    description="Open any installed Windows app, game, launcher, utility, or desktop/Start-menu shortcut by natural application name. Reuse this for Discord, WhatsApp, Spotify, Steam, Calculator, games, and other installed apps.",
    parameters={"type":"object","properties":{"app":{"type":"string"}},"required":["app"]},
)
def system_open_app(app: str) -> ToolResult:
    try:
        data = _system_windows.open_app(app)
    except _system_windows.SystemControlError as exc:
        # Missing apps are an expected user-facing condition, not a tool crash.
        # Keep the underlying launcher unchanged; only translate the resolver's
        # "not found" exception into a clean structured result.
        if "couldn't find an installed app matching" in str(exc).casefold():
            return ToolResult(
                False,
                f"{app} is not installed.",
                {"requested": app, "installed": False, "opened": False},
                error_type="AppNotInstalled",
            )
        raise
    return ToolResult(True, f"Opened {data['name']}.", data)


@tool(
    registry,
    name="system.open_apps",
    description="Open multiple installed Windows applications in one request.",
    parameters={"type":"object","properties":{"apps":{"type":"array","items":{"type":"string"},"minItems":1}},"required":["apps"]},
)
def system_open_apps(apps: list[str]) -> ToolResult:
    data = _system_windows.open_apps(apps)
    opened = [x.get("name", x.get("requested")) for x in data["opened"]]

    parts: list[str] = []
    if opened:
        parts.append("Opened " + ", ".join(str(x) for x in opened) + ".")

    for item in data["errors"]:
        requested = str(item.get("app", "App"))
        error = str(item.get("error", ""))
        if "couldn't find an installed app matching" in error.casefold():
            parts.append(f"{requested} is not installed.")
        else:
            parts.append(f"I couldn't open {requested}.")

    if not parts:
        parts.append("No applications were opened.")

    message = " ".join(parts)
    error_type = None if opened and not data["errors"] else (
        "PartialAppOpen" if opened else "AppNotInstalled"
    )
    return ToolResult(bool(opened), message, data, error_type=error_type)


@tool(
    registry,
    name="system.close_app",
    description="Verify whether an app is running and close it gracefully. If it is not running, report that it is already closed. Never force-kill unsaved interactive work.",
    parameters={"type":"object","properties":{"app":{"type":"string"}},"required":["app"]},
)
def system_close_app(app: str) -> ToolResult:
    data = _system_windows.close_app(app)
    return ToolResult(True, data["message"], data)


@tool(
    registry,
    name="system.close_apps",
    description="Verify and close multiple running Windows applications in one request.",
    parameters={"type":"object","properties":{"apps":{"type":"array","items":{"type":"string"},"minItems":1}},"required":["apps"]},
)
def system_close_apps(apps: list[str]) -> ToolResult:
    data = _system_windows.close_apps(apps)
    messages = [str(x.get("message", "")) for x in data["results"]]
    return ToolResult(True, " ".join(x for x in messages if x), data)


@tool(registry, name="system.volume_get", description="Read the current Windows master volume as a percentage.")
def system_volume_get() -> ToolResult:
    value = _system_windows.volume_get()
    return ToolResult(True, f"System volume is {value}%.", {"volume": value})


@tool(
    registry, name="system.volume_set", description="Set the Windows master volume to an exact percentage.",
    parameters={"type":"object","properties":{"value":{"type":"integer","minimum":0,"maximum":100}},"required":["value"]},
)
def system_volume_set(value: int) -> ToolResult:
    level = _system_windows.volume_set(value)
    return ToolResult(True, f"Set system volume to {level}%.", {"volume": level})


@tool(
    registry, name="system.volume_up", description="Increase Windows master volume by a percentage step.",
    parameters={"type":"object","properties":{"step":{"type":"integer","minimum":1,"maximum":100}}},
)
def system_volume_up(step: int = 10) -> ToolResult:
    level = _system_windows.volume_change(abs(step))
    return ToolResult(True, f"Raised system volume to {level}%.", {"volume": level})


@tool(
    registry, name="system.volume_down", description="Decrease Windows master volume by a percentage step.",
    parameters={"type":"object","properties":{"step":{"type":"integer","minimum":1,"maximum":100}}},
)
def system_volume_down(step: int = 10) -> ToolResult:
    level = _system_windows.volume_change(-abs(step))
    return ToolResult(True, f"Lowered system volume to {level}%.", {"volume": level})


@tool(
    registry, name="system.mute", description="Mute or unmute Windows master audio.",
    parameters={"type":"object","properties":{"muted":{"type":"boolean"}}},
)
def system_mute(muted: bool = True) -> ToolResult:
    state = _system_windows.mute_set(muted)
    return ToolResult(True, "Muted system audio." if state else "Unmuted system audio.", {"muted": state})


@tool(registry, name="system.brightness_get", description="Read the current built-in display brightness percentage.")
def system_brightness_get() -> ToolResult:
    value = _system_windows.brightness_get()
    return ToolResult(True, f"Display brightness is {value}%.", {"brightness": value})


@tool(
    registry, name="system.brightness_set", description="Set built-in display brightness to an exact percentage.",
    parameters={"type":"object","properties":{"value":{"type":"integer","minimum":0,"maximum":100}},"required":["value"]},
)
def system_brightness_set(value: int) -> ToolResult:
    level = _system_windows.brightness_set(value)
    return ToolResult(True, f"Set display brightness to {level}%.", {"brightness": level})


@tool(
    registry, name="system.brightness_up", description="Increase built-in display brightness by a percentage step.",
    parameters={"type":"object","properties":{"step":{"type":"integer","minimum":1,"maximum":100}}},
)
def system_brightness_up(step: int = 10) -> ToolResult:
    level = _system_windows.brightness_change(abs(step))
    return ToolResult(True, f"Raised display brightness to {level}%.", {"brightness": level})


@tool(
    registry, name="system.brightness_down", description="Decrease built-in display brightness by a percentage step.",
    parameters={"type":"object","properties":{"step":{"type":"integer","minimum":1,"maximum":100}}},
)
def system_brightness_down(step: int = 10) -> ToolResult:
    level = _system_windows.brightness_change(-abs(step))
    return ToolResult(True, f"Lowered display brightness to {level}%.", {"brightness": level})


@tool(registry, name="system.wifi_status", description="Read Wi-Fi adapter enabled/connected status.")
def system_wifi_status() -> ToolResult:
    data = _system_windows.wifi_status()
    return ToolResult(True, f"Wi-Fi is {'on' if data['enabled'] else 'off'}" + (" and connected." if data['connected'] else "."), data)


@tool(
    registry, name="system.wifi_toggle", description="Turn Wi-Fi on/off or toggle its current state. Windows may require administrator permission.",
    parameters={"type":"object","properties":{"enabled":{"type":"boolean"}}},
)
def system_wifi_toggle(enabled: bool | None = None) -> ToolResult:
    data = _system_windows.wifi_toggle(enabled)
    return ToolResult(True, f"Wi-Fi is now {'on' if data['enabled'] else 'off'}.", data)


@tool(registry, name="system.dark_mode_get", description="Read whether Windows app/system dark mode is enabled.")
def system_dark_mode_get() -> ToolResult:
    enabled = _system_windows.dark_mode_get()
    return ToolResult(True, f"Dark mode is {'on' if enabled else 'off'}.", {"dark_mode": enabled})


@tool(
    registry, name="system.dark_mode", description="Enable or disable Windows dark mode for apps and system UI.",
    parameters={"type":"object","properties":{"enabled":{"type":"boolean"}},"required":["enabled"]},
)
def system_dark_mode(enabled: bool) -> ToolResult:
    state = _system_windows.dark_mode_set(enabled)
    return ToolResult(True, f"Turned dark mode {'on' if state else 'off'}.", {"dark_mode": state})


@tool(registry, name="system.lock", description="Lock the current Windows workstation immediately.")
def system_lock() -> ToolResult:
    _system_windows.lock_screen()
    return ToolResult(True, "Locked the computer.")


@tool(registry, name="system.restart", description="Restart the Windows computer. This always requires explicit user confirmation.", risk=ToolRisk.CONFIRM)
def system_restart() -> ToolResult:
    _system_windows.restart_computer()
    return ToolResult(True, "Restarting the computer.")


@tool(registry, name="system.shutdown", description="Shut down the Windows computer. This always requires explicit user confirmation.", risk=ToolRisk.CONFIRM)
def system_shutdown() -> ToolResult:
    _system_windows.shutdown_computer()
    return ToolResult(True, "Shutting down the computer.")


@tool(registry, name="system.sleep_display", description="Turn off/sleep the display without shutting down the computer.")
def system_sleep_display() -> ToolResult:
    _system_windows.sleep_display()
    return ToolResult(True, "Put the display to sleep.")


@tool(
    registry, name="system.open_settings", description="Open Windows Settings, optionally at a specific ms-settings page suffix.",
    parameters={"type":"object","properties":{"page":{"type":"string"}}},
)
def system_open_settings(page: str = "") -> ToolResult:
    _system_windows.open_settings(page)
    return ToolResult(True, "Opened Windows Settings.", {"page": page})


@tool(registry, name="system.open_task_manager", description="Open Windows Task Manager.")
def system_open_task_manager() -> ToolResult:
    _system_windows.open_task_manager()
    return ToolResult(True, "Opened Task Manager.")


@tool(registry, name="system.show_desktop", description="Show the Windows desktop using Win+D.")
def system_show_desktop() -> ToolResult:
    _system_windows.show_desktop()
    return ToolResult(True, "Showed the desktop.")


@tool(
    registry, name="system.snap_window", description="Snap the currently focused window to the left or right half of the screen.",
    parameters={"type":"object","properties":{"direction":{"type":"string","enum":["left","right"]}},"required":["direction"]},
)
def system_snap_window(direction: str) -> ToolResult:
    value = _system_windows.snap_window(direction)
    return ToolResult(True, f"Snapped the active window {value}.", {"direction": value})


@tool(registry, name="system.switch_windows", description="Switch to the previous/next application window using Alt+Tab.")
def system_switch_windows() -> ToolResult:
    _system_windows.switch_windows()
    return ToolResult(True, "Switched windows.")


@tool(
    registry, name="system.browser_zoom", description="Zoom the currently focused browser/page in, out, or reset to 100 percent.",
    parameters={"type":"object","properties":{"action":{"type":"string","enum":["in","out","reset"]}},"required":["action"]},
)
def system_browser_zoom(action: str) -> ToolResult:
    value = _system_windows.browser_zoom(action)
    return ToolResult(True, f"Browser zoom {value}.", {"action": value})


@tool(
    registry, name="system.browser_tab_shortcut", description="Use a native browser tab shortcut: next, previous, new, close, or reopen.",
    parameters={"type":"object","properties":{"action":{"type":"string","enum":["next","previous","new","close","reopen"]}},"required":["action"]},
)
def system_browser_tab_shortcut(action: str) -> ToolResult:
    value = _system_windows.browser_tab_shortcut(action)
    return ToolResult(True, f"Browser tab action: {value}.", {"action": value})


@tool(
    registry, name="system.page_navigation", description="Use native page navigation shortcut: back, forward, or reload.",
    parameters={"type":"object","properties":{"action":{"type":"string","enum":["back","forward","reload"]}},"required":["action"]},
)
def system_page_navigation(action: str) -> ToolResult:
    value = _system_windows.page_navigation(action)
    return ToolResult(True, f"Page navigation: {value}.", {"action": value})



# ---------------------------------------------------------------------------
# Advanced file processing
# ---------------------------------------------------------------------------

@tool(
    registry,
    name="file.set_active",
    description=(
        "Set the active file for subsequent file-processing actions. This is also "
        "the backend hook the future GUI drag-and-drop feature will call."
    ),
    parameters={
        "type":"object",
        "properties":{
            "path":{"type":"string"},
            "source":{"type":"string","enum":["filesystem","gui_drop","attachment","clipboard","unknown"]},
            "temporary":{"type":"boolean"}
        },
        "required":["path"]
    },
)
def file_set_active(path: str, source: str = "filesystem", temporary: bool = False) -> ToolResult:
    try:
        item = file_service.set_active_file(path, source=source, temporary=temporary)
    except Exception as exc:
        return ToolResult(False, str(exc), {"path": path}, error_type=type(exc).__name__)
    return ToolResult(
        True,
        f"Active file is now {item.original_name}.",
        {"file": item.data()},
    )


@tool(
    registry,
    name="file.get_active",
    description="Return the current active file used by 'this file', GUI-drop, and follow-up processing requests.",
)
def file_get_active() -> ToolResult:
    item = file_service.get_active_file()
    if item is None:
        return ToolResult(False, "No active file is set.", {"file": None}, error_type="NoActiveFile")
    return ToolResult(True, f"Active file is {item.original_name}.", {"file": item.data()})


@tool(
    registry,
    name="file.capabilities",
    description="Detect a file type and list the processing actions Conduit supports for it.",
    parameters={
        "type":"object",
        "properties":{"path":{"type":"string"}},
    },
)
def file_capabilities(path: str = "") -> ToolResult:
    try:
        data = file_service.capabilities(path or None)
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)
    return ToolResult(
        True,
        f"Supported actions for this {data['file']['kind']} file: {', '.join(data['actions'])}.",
        data,
    )


@tool(
    registry,
    name="file.process",
    description=(
        "Process a file using Conduit's format-specific adapters. The path is optional "
        "when an active file is already set (for example by a future GUI drop). "
        "Actions include image resize/compress/convert/OCR/describe; PDF extract/summarize/"
        "analyze/to_word; document summarize/fix/reformat/translate/word_count/bullet_points; "
        "spreadsheet analyze/statistics/filter/sort/convert; JSON/XML validate/format/analyze/"
        "convert_csv; audio/video inspect/trim/convert/transcribe/extract_audio/extract_frame/"
        "compress; archive list/extract; presentation extract_text/summarize/analyze."
    ),
    parameters={
        "type":"object",
        "properties":{
            "action":{"type":"string"},
            "path":{"type":"string"},
            "parameters":{"type":"object"}
        },
        "required":["action"]
    },
)
def file_process(action: str, path: str = "", parameters: dict | None = None) -> ToolResult:
    try:
        result = file_service.process(
            action=action,
            path=path or None,
            parameters=parameters or {},
        )
    except DependencyUnavailable as exc:
        return ToolResult(False, str(exc), error_type="DependencyUnavailable")
    except FileProcessingError as exc:
        return ToolResult(False, str(exc), error_type="FileProcessingError")
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)

    data = result.as_dict()
    # Avoid flooding the agent context with entire documents. Semantic operations
    # are completed by ConversationSession using the active provider.
    if "semantic_text" in data:
        text = str(data["semantic_text"])
        data["semantic_text_preview"] = text[:8000]
        data["semantic_text_characters"] = len(text)
        data.pop("semantic_text", None)

    return ToolResult(result.success, result.message, data)



# ---------------------------------------------------------------------------
# Single-file Code Helper
# ---------------------------------------------------------------------------

@tool(
    registry, name="code.generate",
    description="Create a single code file from already-generated source content. Defaults to the user's Desktop when path is omitted.",
    parameters={"type":"object","properties":{"language":{"type":"string"},"content":{"type":"string"},"prompt":{"type":"string"},"filename":{"type":"string"},"path":{"type":"string"}},"required":["language","content"]},
)
def code_generate(language: str, content: str, prompt: str = "generated code", filename: str = "", path: str = "") -> ToolResult:
    try:
        content = code_service.strip_code_fences(content)
        if not content.strip():
            return ToolResult(False, "Refusing to create an empty code file.", error_type="CodeHelperError")
        valid, error = code_service.validate_source(content, language=language)
        if not valid:
            return ToolResult(False, f"Generated source failed validation: {error}", error_type="CodeValidationError")
        target=code_service.write_generated(content,language=language,prompt=prompt,filename=filename,path=path)
        return ToolResult(True,f"Generated code file at {target}.",{"path":str(target),"language":language})
    except Exception as exc:
        return ToolResult(False,str(exc),error_type=type(exc).__name__)

@tool(
    registry, name="code.edit",
    description="Replace a single existing code file with provided source content and create a backup first.",
    parameters={"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["content"]},
)
def code_edit(content: str, path: str = "") -> ToolResult:
    try:
        target,backup=code_service.replace(content,path or None,create_backup=True)
        return ToolResult(True,f"Updated {target}.",{"path":str(target),"backup":str(backup or "")})
    except Exception as exc:
        return ToolResult(False,str(exc),error_type=type(exc).__name__)

@tool(registry, name="code.read_file", description="Read one code file and return its detected language and source.", parameters={"type":"object","properties":{"path":{"type":"string"}}})
def code_read_file(path: str = "") -> ToolResult:
    try:
        target=code_service.resolve_code_file(path or None); source=code_service.read(target)
        return ToolResult(True,f"Read {target.name}.",{"path":str(target),"language":code_service.detect_language(target),"source":source[:20000]})
    except Exception as exc: return ToolResult(False,str(exc),error_type=type(exc).__name__)

@tool(registry, name="code.explain", description="Load a single code file for explanation by the agent.", parameters={"type":"object","properties":{"path":{"type":"string"}}})
def code_explain(path: str = "") -> ToolResult:
    try:
        target=code_service.resolve_code_file(path or None); source=code_service.read(target)
        return ToolResult(True,f"Loaded {target.name} for explanation.",{"path":str(target),"language":code_service.detect_language(target),"source":source[:20000]})
    except Exception as exc: return ToolResult(False,str(exc),error_type=type(exc).__name__)

@tool(registry, name="code.review", description="Load a single code file for code review by the agent.", parameters={"type":"object","properties":{"path":{"type":"string"}}})
def code_review(path: str = "") -> ToolResult:
    return code_explain(path)

@tool(registry, name="code.run", description="Run a single code file with Conduit's restricted language-specific runner and capture stdout/stderr.", parameters={"type":"object","properties":{"path":{"type":"string"},"timeout":{"type":"number"}}})
def code_run(path: str = "", timeout: float = 20.0) -> ToolResult:
    result=code_service.run(path or None,timeout=timeout)
    return ToolResult(result.success,result.message,{"language":result.language,"path":str(result.path),"exit_code":result.exit_code,"stdout":result.stdout,"stderr":result.stderr,"error_category":result.category.value,"command":list(result.command)})

@tool(registry, name="code.test", description="Compile/syntax-check and execute a single code file as a single-file test.", parameters={"type":"object","properties":{"path":{"type":"string"},"timeout":{"type":"number"}}})
def code_test(path: str = "", timeout: float = 20.0) -> ToolResult:
    result=code_service.test(path or None,timeout=timeout)
    return ToolResult(result.success,result.message,{"language":result.language,"path":str(result.path),"exit_code":result.exit_code,"stdout":result.stdout,"stderr":result.stderr,"error_category":result.category.value})

@tool(registry, name="code.debug", description="Run a single code file and return a structured error classification for repair.", parameters={"type":"object","properties":{"path":{"type":"string"}}})
def code_debug(path: str = "") -> ToolResult:
    result=code_service.run(path or None)
    return ToolResult(result.success,result.message,{"language":result.language,"path":str(result.path),"exit_code":result.exit_code,"stdout":result.stdout,"stderr":result.stderr,"error_category":result.category.value})

@tool(registry, name="code.optimize", description="Load a single code file so the agent can generate an optimized replacement.", parameters={"type":"object","properties":{"path":{"type":"string"}}})
def code_optimize(path: str = "") -> ToolResult:
    return code_explain(path)

@tool(
    registry, name="code.install_dependency",
    description="Install one validated dependency for the single-file code helper. Requires explicit tool confirmation.",
    parameters={"type":"object","properties":{"package":{"type":"string"},"language":{"type":"string"}},"required":["package","language"]},
    risk=ToolRisk.CONFIRM,
)
def code_install_dependency(package: str, language: str) -> ToolResult:
    try:
        result=code_service.install_dependency(package,language=language)
        return ToolResult(result.success,result.message,{"stdout":result.stdout,"stderr":result.stderr,"error_category":result.category.value})
    except Exception as exc: return ToolResult(False,str(exc),error_type=type(exc).__name__)


# ---------------------------------------------------------------------------
# Multi-file Developer Agent mechanical actions
# ---------------------------------------------------------------------------

@tool(
    registry,
    name="dev.plan_project",
    description="Normalize/validate an already-designed multi-file project plan for the Developer Agent.",
    parameters={
        "type":"object",
        "properties":{
            "name":{"type":"string"},
            "language":{"type":"string"},
            "framework":{"type":"string"},
            "description":{"type":"string"},
            "entry_point":{"type":"string"},
            "dependencies":{"type":"array","items":{"type":"string"}},
            "files":{"type":"array","items":{"type":"object"}},
            "test_strategy":{"type":"string"},
        },
        "required":["name","language","files"],
    },
)
def dev_plan_project(
    name: str,
    language: str,
    files: list,
    framework: str = "",
    description: str = "",
    entry_point: str = "",
    dependencies: list | None = None,
    test_strategy: str = "",
) -> ToolResult:
    try:
        clean_files = []
        for row in files[:30]:
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or "")
            dev_service._safe_relpath(path)
            clean_files.append({
                "path": path,
                "purpose": str(row.get("purpose") or ""),
            })
        if not clean_files:
            raise DeveloperAgentError("Project plan requires at least one valid file.")
        plan = ProjectPlan(
            name=dev_service.safe_project_name(name),
            language=language,
            framework=framework,
            description=description,
            entry_point=entry_point,
            dependencies=[str(x) for x in (dependencies or [])],
            files=clean_files,
            test_strategy=test_strategy,
        )
        return ToolResult(True, "Validated multi-file project plan.", plan.as_dict())
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="dev.create_project",
    description="Create a multi-file project from a validated map of relative file paths to complete file contents.",
    parameters={
        "type":"object",
        "properties":{
            "project_name":{"type":"string"},
            "files":{"type":"object"},
            "path":{"type":"string"},
            "plan":{"type":"object"},
        },
        "required":["project_name","files"],
    },
)
def dev_create_project(project_name: str, files: dict, path: str = "", plan: dict | None = None) -> ToolResult:
    try:
        root = dev_service.create_from_files(
            project_name=project_name,
            files={str(k): str(v) for k,v in files.items()},
            plan=plan or {},
            path=path,
        )
        info = dev_service.inspect(root)
        return ToolResult(
            True,
            f"Created multi-file project at {root}.",
            {"root":str(root),"kind":info.kind.value,"files":info.files,"entry_point":info.entry_point},
        )
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="dev.inspect_project",
    description="Inspect the active multi-file project: type, entry point, dependency files, tests and file tree.",
    parameters={"type":"object","properties":{"path":{"type":"string"}}},
)
def dev_inspect_project(path: str = "") -> ToolResult:
    try:
        data = dev_service.manifest_summary(path or None)
        return ToolResult(True, f"Inspected project {data['name']}.", data)
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="dev.install_dependencies",
    description="Install dependency metadata for the active Python or Node project using a restricted ecosystem command. Requires explicit confirmation.",
    parameters={"type":"object","properties":{"path":{"type":"string"},"timeout":{"type":"number"}}},
    risk=ToolRisk.CONFIRM,
)
def dev_install_dependencies(path: str = "", timeout: float = 300.0) -> ToolResult:
    try:
        result = dev_service.install_dependencies(path or None, timeout=timeout)
        return ToolResult(
            result.success,
            result.message,
            {
                "command":list(result.command),
                "exit_code":result.exit_code,
                "stdout":result.stdout,
                "stderr":result.stderr,
                "error_category":result.category.value,
            },
        )
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="dev.run_project",
    description="Run the active multi-file project using its detected safe language-specific entry point and capture stdout/stderr.",
    parameters={"type":"object","properties":{"path":{"type":"string"},"timeout":{"type":"number"}}},
)
def dev_run_project(path: str = "", timeout: float = 30.0) -> ToolResult:
    try:
        result = dev_service.run_project(path or None, timeout=timeout)
        return ToolResult(
            result.success,
            result.message,
            {
                "root":str(result.root),
                "command":list(result.command),
                "exit_code":result.exit_code,
                "stdout":result.stdout,
                "stderr":result.stderr,
                "error_category":result.category.value,
            },
        )
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="dev.run_tests",
    description="Run the detected project-level test suite in the active multi-file project and capture results.",
    parameters={"type":"object","properties":{"path":{"type":"string"},"timeout":{"type":"number"}}},
)
def dev_run_tests(path: str = "", timeout: float = 60.0) -> ToolResult:
    try:
        result = dev_service.run_tests(path or None, timeout=timeout)
        return ToolResult(
            result.success,
            result.message,
            {
                "root":str(result.root),
                "command":list(result.command),
                "exit_code":result.exit_code,
                "stdout":result.stdout,
                "stderr":result.stderr,
                "error_category":result.category.value,
            },
        )
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="dev.analyze_error",
    description="Classify a captured multi-file project error mechanically before AI repair.",
    parameters={
        "type":"object",
        "properties":{
            "stderr":{"type":"string"},
            "stdout":{"type":"string"},
            "exit_code":{"type":"integer"},
        },
    },
)
def dev_analyze_error(stderr: str = "", stdout: str = "", exit_code: int = 1) -> ToolResult:
    category = dev_service.classify_error(stderr or stdout, exit_code)
    return ToolResult(
        True,
        f"Classified project failure as {category.value}.",
        {"error_category":category.value},
    )


@tool(
    registry,
    name="dev.patch_files",
    description="Replace one or more files inside the active project. Paths must remain inside the project and existing files are backed up.",
    parameters={
        "type":"object",
        "properties":{
            "patches":{"type":"object"},
            "path":{"type":"string"},
        },
        "required":["patches"],
    },
)
def dev_patch_files(patches: dict, path: str = "") -> ToolResult:
    try:
        written = dev_service.patch_files(
            {str(k):str(v) for k,v in patches.items()},
            path or None,
        )
        return ToolResult(
            True,
            f"Patched {len(written)} project file(s).",
            {"files":[str(x) for x in written]},
        )
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="dev.open_editor",
    description="Open the active multi-file project folder in Visual Studio Code using the local code CLI.",
    parameters={"type":"object","properties":{"path":{"type":"string"}}},
)
def dev_open_editor(path: str = "") -> ToolResult:
    try:
        message = dev_service.open_editor(path or None)
        return ToolResult(True, message)
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


# ---------------------------------------------------------------------------
# Steam / Epic Games management
# ---------------------------------------------------------------------------

@tool(
    registry,
    name="games.list",
    description="List games installed through Steam and Epic Games Launcher using local launcher manifests.",
)
def games_list() -> ToolResult:
    try:
        rows = games_service.list_installed()
        return ToolResult(
            True,
            f"Found {len(rows)} installed game(s).",
            {"games": [game.data() for game in rows]},
        )
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="games.install",
    description="Start a Steam installation by app ID or open the Steam/Epic launcher to install a named game.",
    parameters={
        "type":"object",
        "properties":{
            "game":{"type":"string"},
            "platform":{"type":"string","enum":["steam","epic"]},
        },
        "required":["game"],
    },
)
def games_install(game: str, platform: str = "steam") -> ToolResult:
    try:
        message = games_service.install(game, platform=platform)
        return ToolResult(True, message, {"game":game,"platform":platform})
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="games.update",
    description="Update an installed Steam/Epic game. Returns 'No update available' when local launcher state reports the game is current.",
    parameters={
        "type":"object",
        "properties":{
            "game":{"type":"string"},
            "platform":{"type":"string","enum":["steam","epic"]},
        },
        "required":["game"],
    },
)
def games_update(game: str, platform: str = "") -> ToolResult:
    try:
        item = games_service.find_game(game, platform=platform)
        message, status = games_service.update(item)
        return ToolResult(True, message, status.data())
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="games.download_status",
    description="Inspect local Steam/Epic download/update state for an installed game.",
    parameters={
        "type":"object",
        "properties":{
            "game":{"type":"string"},
            "platform":{"type":"string","enum":["steam","epic"]},
        },
        "required":["game"],
    },
)
def games_download_status(game: str, platform: str = "") -> ToolResult:
    try:
        item = games_service.find_game(game, platform=platform)
        status = games_service.download_status(item)
        return ToolResult(True, status.message, status.data())
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="games.schedule_update",
    description="Schedule a one-time Windows update task for an installed Steam/Epic game.",
    parameters={
        "type":"object",
        "properties":{
            "game":{"type":"string"},
            "when":{"type":"string"},
            "platform":{"type":"string","enum":["steam","epic"]},
        },
        "required":["game","when"],
    },
)
def games_schedule_update(game: str, when: str, platform: str = "") -> ToolResult:
    try:
        item = games_service.find_game(game, platform=platform)
        message = games_service.schedule_update(item, when=when)
        return ToolResult(True, message, {"game":item.data(),"when":when})
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="games.cancel_schedule",
    description="Cancel Conduit's scheduled update task for an installed game.",
    parameters={
        "type":"object",
        "properties":{
            "game":{"type":"string"},
            "platform":{"type":"string","enum":["steam","epic"]},
        },
        "required":["game"],
    },
)
def games_cancel_schedule(game: str, platform: str = "") -> ToolResult:
    try:
        item = games_service.find_game(game, platform=platform)
        message = games_service.cancel_schedule(item)
        return ToolResult(True, message, {"game":item.data()})
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="games.launch",
    description="Launch an installed Steam or Epic game through its launcher protocol.",
    parameters={
        "type":"object",
        "properties":{
            "game":{"type":"string"},
            "platform":{"type":"string","enum":["steam","epic"]},
        },
        "required":["game"],
    },
)
def games_launch(game: str, platform: str = "") -> ToolResult:
    try:
        item = games_service.find_game(game, platform=platform)
        message = games_service.launch(item)
        return ToolResult(True, message, {"game":item.data()})
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


# ---------------------------------------------------------------------------
# Conduit environment / first-run setup
# ---------------------------------------------------------------------------

@tool(
    registry,
    name="environment.check",
    description="Check Conduit's Python dependencies, browser runtime, Ollama installation and recommended local models.",
)
def environment_check() -> ToolResult:
    try:
        data = environment_service.check_all()
        return ToolResult(True, "Checked Conduit's runtime environment.", data)
    except Exception as exc:
        return ToolResult(False, str(exc), error_type=type(exc).__name__)


@tool(
    registry,
    name="environment.install_optional_feature",
    description="Install one of Conduit's optional Python feature dependency groups such as OCR or local transcription.",
    parameters={
        "type":"object",
        "properties":{
            "feature":{"type":"string","enum":["ocr","local_transcription"]},
        },
        "required":["feature"],
    },
    risk=ToolRisk.CONFIRM,
)
def environment_install_optional_feature(feature: str) -> ToolResult:
    ok, message = environment_service.install_optional_feature(feature)
    return ToolResult(ok, message)


@tool(
    registry,
    name="environment.verify_browser",
    description="Verify that Playwright and its Chromium browser runtime are installed for Conduit's managed browser.",
)
def environment_verify_browser() -> ToolResult:
    row = environment_service.verify_browser()
    return ToolResult(row.available, row.detail, row.data())


@tool(
    registry,
    name="environment.verify_ollama",
    description="Verify whether Ollama is installed and locatable on this PC.",
)
def environment_verify_ollama() -> ToolResult:
    row = environment_service.verify_ollama()
    return ToolResult(row.available, row.detail, row.data())


@tool(
    registry,
    name="environment.verify_model",
    description="Verify whether a named Ollama model is installed locally.",
    parameters={
        "type":"object",
        "properties":{"model":{"type":"string"}},
        "required":["model"],
    },
)
def environment_verify_model(model: str) -> ToolResult:
    row = environment_service.verify_model(model)
    return ToolResult(row.available, row.detail, row.data())
