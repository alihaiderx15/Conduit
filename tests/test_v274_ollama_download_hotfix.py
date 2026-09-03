import ast
from pathlib import Path

def test_ollama_downloader_has_subprocess_import():
    root=Path(__file__).resolve().parents[1]
    source=(root/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    tree=ast.parse(source)
    imports={a.name for n in tree.body if isinstance(n,ast.Import) for a in n.names}
    assert "subprocess" in imports
    assert "subprocess.Popen(" in source
