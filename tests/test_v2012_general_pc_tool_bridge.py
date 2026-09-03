
from conduit.general_pc.agent import GeneralPCAgent


def test_general_pc_agent_exposes_router_tool_executor():
    agent = object.__new__(GeneralPCAgent)
    fake_tools = object()
    agent.router = type("Router", (), {"tools": fake_tools})()
    assert agent.tools is fake_tools
