import pytest
from conduit.tools.errors import DuplicateToolError, ToolNotFoundError
from conduit.tools.registry import ToolRegistry, tool

def test_registration_and_definition():
    r=ToolRegistry()
    @tool(r,name="echo",description="Echo",parameters={"type":"object","properties":{"text":{"type":"string"}},"required":["text"]})
    def echo(text:str): return text
    assert r.get("echo").handler("x")=="x"
    assert r.definitions()[0].name=="echo"

def test_duplicate_rejected():
    r=ToolRegistry()
    @tool(r,name="same",description="one")
    def one(): pass
    with pytest.raises(DuplicateToolError):
        @tool(r,name="same",description="two")
        def two(): pass

def test_missing_rejected():
    with pytest.raises(ToolNotFoundError): ToolRegistry().get("missing")
