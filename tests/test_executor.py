from conduit.core.models import ToolCall
from conduit.execution import ToolExecutor
from conduit.tools.models import PendingConfirmation, ToolResult, ToolRisk
from conduit.tools.registry import ToolRegistry, tool

async def test_safe_executes():
    r=ToolRegistry()
    @tool(r,name="add",description="Add",parameters={"type":"object","properties":{"a":{"type":"integer"},"b":{"type":"integer"}},"required":["a","b"]})
    def add(a:int,b:int): return a+b
    result=await ToolExecutor(r).execute(ToolCall("add",{"a":2,"b":3}))
    assert isinstance(result,ToolResult) and result.success and result.data["result"]==5

async def test_confirmation_pauses_then_runs():
    r=ToolRegistry(); calls=[]
    @tool(r,name="write",description="Write",risk=ToolRisk.CONFIRM)
    def write(): calls.append(1); return ToolResult(True,"ok")
    ex=ToolExecutor(r)
    assert isinstance(await ex.execute(ToolCall("write",{})),PendingConfirmation)
    assert calls==[]
    assert (await ex.execute(ToolCall("write",{}),confirmed=True)).success
    assert calls==[1]

async def test_invalid_arguments_block_handler():
    r=ToolRegistry(); calls=[]
    @tool(r,name="repeat",description="Repeat",parameters={"type":"object","properties":{"count":{"type":"integer","minimum":1}},"required":["count"]})
    def repeat(count:int): calls.append(1)
    result=await ToolExecutor(r).execute(ToolCall("repeat",{"count":0}))
    assert not result.success and result.error_type=="ToolValidationError" and calls==[]
