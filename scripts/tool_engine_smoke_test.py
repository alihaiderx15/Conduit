from __future__ import annotations
import argparse, asyncio
from conduit.core.models import ToolCall
from conduit.execution import ToolExecutor
from conduit.tools.builtin import registry
async def main():
    parser=argparse.ArgumentParser(); parser.add_argument("test",choices=("calculator","confirmation")); args=parser.parse_args()
    executor=ToolExecutor(registry)
    call=ToolCall("open_calculator",{}) if args.test=="calculator" else ToolCall("create_folder",{"path":"Conduit Smoke Test"})
    print(await executor.execute(call))
if __name__=="__main__": asyncio.run(main())
