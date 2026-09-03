import json
import pytest
from conduit.core.models import ProviderCapabilities, ProviderResponse
from conduit.planning import TaskPlanner, parse_plan, PlanValidationError
from conduit.providers.base import AIProvider


class FakeProvider(AIProvider):
    provider_id = "fake"
    def __init__(self, outputs): self.outputs=list(outputs)
    @property
    def capabilities(self): return ProviderCapabilities()
    async def list_models(self): return ["fake"]
    async def chat(self, messages, *, model, tools=()): return ProviderResponse(text=self.outputs.pop(0), model=model)


def valid_payload():
    return json.dumps({
        "goal":"Open calculator", "summary":"Open it", "assumptions":[],
        "steps":[{"id":"step_1","title":"Open Calculator","capability":"tool","action":"open_calculator","arguments":{},"depends_on":[],"requires_confirmation":False,"success_criteria":"Calculator window opens"}]
    })


def test_parse_valid_plan():
    plan=parse_plan(valid_payload(), allowed_actions=["open_calculator"])
    assert plan.steps[0].action == "open_calculator"


def test_rejects_unavailable_action():
    with pytest.raises(PlanValidationError):
        parse_plan(valid_payload(), allowed_actions=["something_else"])


def test_rejects_forward_dependency():
    payload=json.loads(valid_payload())
    payload["steps"][0]["depends_on"]=["step_2"]
    with pytest.raises(PlanValidationError):
        parse_plan(json.dumps(payload), allowed_actions=["open_calculator"])


@pytest.mark.asyncio
async def test_planner_returns_structured_plan():
    planner=TaskPlanner(provider=FakeProvider([valid_payload()]), model="fake")
    plan=await planner.create_plan("Open calculator")
    assert plan.goal == "Open calculator"
    assert len(plan.steps) == 1


@pytest.mark.asyncio
async def test_planner_retries_invalid_json():
    planner=TaskPlanner(provider=FakeProvider(["not json", valid_payload()]), model="fake")
    plan=await planner.create_plan("Open calculator")
    assert plan.steps[0].action == "open_calculator"
