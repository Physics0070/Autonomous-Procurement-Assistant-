"""LLM council: a different model per task, and a council whose members read each
other's answers before a monitor model writes the final one."""
import json

import pytest

from app.core.config import settings
from app.integrations.ai import factory
from app.integrations.ai.base import AIResponse, UnconfiguredProvider
from app.integrations.ai.council import CouncilProvider
from tests.fakes.llm import ScriptedProvider


@pytest.fixture
def openrouter(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(settings, "OPENROUTER_MODEL", "base/model")
    monkeypatch.setattr(settings, "LLM_TASK_MODELS", "negotiation=vendor/negotiator, critic=council")
    monkeypatch.setattr(settings, "COUNCIL_MODELS", "a/one, b/two, c/three")
    monkeypatch.setattr(settings, "COUNCIL_MONITOR_MODEL", "m/monitor")
    factory.reset_ai_provider()
    yield
    factory.reset_ai_provider()


def test_each_task_can_use_its_own_model(openrouter):
    assert factory.get_ai_provider("negotiation").model == "vendor/negotiator"
    assert factory.get_ai_provider("extraction").model == "base/model"  # no override -> the default
    council = factory.get_ai_provider("critic")
    assert isinstance(council, CouncilProvider)
    assert [m.model for m in council.members] == ["a/one", "b/two", "c/three"]
    assert council.monitor.model == "m/monitor"


def test_without_a_key_every_task_says_so(openrouter, monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    factory.reset_ai_provider()
    for task in ("negotiation", "critic", "extraction"):
        assert isinstance(factory.get_ai_provider(task), UnconfiguredProvider)


def test_an_injected_provider_is_never_swapped(openrouter):
    injected = ScriptedProvider()
    assert factory.for_task(injected, "negotiation") is injected
    assert factory.for_task(factory.get_ai_provider(), "negotiation").model == "vendor/negotiator"


def member(name, first, revised, seen):
    """A council member that answers, then revises after reading the others."""
    def reply(prompt, system):
        seen.setdefault(name, []).append(prompt)
        return first if len(seen[name]) == 1 else revised
    provider = ScriptedProvider(responder=reply)
    provider.model = name
    return provider


async def test_members_read_each_others_answers_before_the_monitor_decides():
    seen: dict[str, list[str]] = {}
    members = [member("a/one", "Pick Shree: cheapest.", "Pick Shree, but check delivery.", seen),
               member("b/two", "Pick Apex: fastest.", "Shree after all; Apex is late.", seen),
               member("c/three", "Pick Shree.", "Shree.", seen)]
    monitor = ScriptedProvider(responses=['{"summary": "Shree Steel, with a delivery check."}'])
    monitor.model = "m/monitor"

    result = await CouncilProvider(members, monitor).generate("Who should we buy from?", system="Be brief.")

    assert result.ok and result.provider == "council"
    assert result.text == '{"summary": "Shree Steel, with a delivery check."}'
    # Round 2: each member saw the other two answers - never its own - under an anonymous label.
    second_round_of_a = seen["a/one"][1]
    assert "Pick Apex: fastest." in second_round_of_a and "Pick Shree." in second_round_of_a
    assert "Pick Shree: cheapest." not in second_round_of_a
    assert "b/two" not in second_round_of_a  # anonymous: no model names leak between members
    # The monitor read every revised answer.
    monitor_prompt = monitor.calls[0]["prompt"]
    for revised in ("Pick Shree, but check delivery.", "Shree after all; Apex is late.", "Shree."):
        assert revised in monitor_prompt
    transcript = result.meta["transcript"]
    assert [step["round"] for step in transcript] == ["answer"] * 3 + ["review"] * 3 + ["decision"]


async def test_a_failing_member_is_dropped_and_the_council_carries_on():
    seen: dict[str, list[str]] = {}
    broken = ScriptedProvider(responses=[AIResponse(ok=False, error="429 rate limited")])
    broken.model = "x/broken"
    members = [member("a/one", "A", "A2", seen), member("b/two", "B", "B2", seen), broken]
    monitor = ScriptedProvider(responses=["final"])
    result = await CouncilProvider(members, monitor).generate("q")
    assert result.ok and result.text == "final"
    assert any("x/broken" in note for note in result.meta["dropped"])


async def test_with_fewer_than_two_answers_there_is_no_council_to_hold():
    one = ScriptedProvider(responses=["only me"])
    dead = ScriptedProvider(responses=[AIResponse(ok=False, error="down")])
    result = await CouncilProvider([one, dead], ScriptedProvider()).generate("q")
    assert not result.ok and "at least two" in result.error


async def test_explanations_record_the_councils_deliberation(monkeypatch):
    """The recommendation explanation can be written by a council, with its transcript kept."""
    from app.schemas.comparison import ComparisonResult, SupplierScore
    from app.services.procurement.explanation import explain_comparison

    seen: dict[str, list[str]] = {}
    answer = json.dumps({"summary": "Shree Steel ranks first.", "reasoning": ["cheapest"], "risks": []})
    members = [member("a/one", answer, answer, seen), member("b/two", answer, answer, seen)]
    council = CouncilProvider(members, ScriptedProvider(responses=[answer]))
    comparison = ComparisonResult(procurement_request_id="r1", suppliers=[
        SupplierScore(quotation_id="q1", supplier_name="Shree Steel", rank=1, overall_score=0.8)])

    explanation = await explain_comparison(comparison, council)
    assert explanation.provider == "council"
    assert explanation.summary == "Shree Steel ranks first."
    assert len(explanation.deliberation) == 5  # 2 answers, 2 reviews, 1 decision


async def test_a_council_reviews_drafts_inside_a_real_agent_run(api, sourcing, monkeypatch):
    """Each task gets its own provider; the critic is a council whose monitor rejects the draft."""
    from tests.fakes.llm import answer, tool_call

    single = ScriptedProvider(
        chat_responses=[tool_call("submit_draft", {"subject": "Offer", "body": "Please revise your price."}),
                        answer("submitted")],
        responder=lambda prompt, system: "{}")  # routing and explanation: nothing useful, policy takes over
    seen: dict[str, list[str]] = {}
    approve = json.dumps({"approved": True, "issues": []})
    reject = json.dumps({"approved": False, "issues": ["Too vague: no figure is asked for."]})
    council = CouncilProvider([member("a/one", approve, reject, seen), member("b/two", approve, reject, seen)],
                              ScriptedProvider(responses=[reject]))
    for task in (None, "extraction", "matching", "recommendation", "supervisor", "drafting", "negotiation", "assistant"):
        monkeypatch.setitem(factory._providers, task, single)
    monkeypatch.setitem(factory._providers, "critic", council)

    run = (await api.post(f"/api/v1/agents/supervisor/{sourcing['request']['id']}", headers=sourcing["headers"])).json()

    critic = next(s for s in run["steps"] if s["agent"] == "Critic Agent")
    assert "Too vague" in critic["summary"]
    assert len(seen["a/one"]) == 2 and len(seen["b/two"]) == 2  # both members answered and reviewed
    draft = (await api.get("/api/v1/communications", headers=sourcing["headers"])).json()[0]
    assert draft["generated_by"] == "template"  # the council's rejection sent it back to the safe template
