"""What a hostile quotation or e-mail could make a model ask for, and why it does not happen.

The model only chooses among listed tools; nothing it can call approves, sends or issues anything; arguments it adds to
widen a tool's scope are dropped; and the approval that lets an agent run continue needs an approver's role."""
import asyncio

import pytest

from app.services.agents.loop import call_method

API = "/api/v1"
SIDE_EFFECT_WORDS = ("approve", "send", "issue", "pay", "delete", "accept", "sign")


def test_no_tool_a_model_can_call_has_a_side_effect():
    from app.services.agents.assistant import TOOLS
    from app.services.agents.specialists import NEGOTIATION_TOOLS

    names = [t["function"]["name"] for t in TOOLS + NEGOTIATION_TOOLS]
    assert not [n for n in names if any(w in n for w in SIDE_EFFECT_WORDS)]


class _Tools:
    def __init__(self):
        self.seen = None

    async def get_quotation(self, quotation_id: str):
        self.seen = quotation_id
        return {"id": quotation_id}

    async def approve_purchase_order(self, po_id: str):  # exists on the object, but is not offered to the model
        raise AssertionError("must never run")


@pytest.mark.parametrize("name", ["approve_purchase_order", "__init__", "__class__", "_private", "get_quotation "])
def test_a_tool_that_was_not_offered_is_refused(name):
    result = asyncio.run(call_method(_Tools(), {"get_quotation"}, name, {"po_id": "x"}))
    assert result == {"error": f"Unknown tool {name}."}


def test_arguments_that_widen_a_tool_are_dropped():
    tools = _Tools()
    result = asyncio.run(call_method(tools, {"get_quotation"}, "get_quotation",
                                     {"quotation_id": "q1", "organization_id": "someone-else", "bypass_approval": True}))
    assert result == {"id": "q1"} and tools.seen == "q1"


async def test_a_member_cannot_approve_a_paused_agent_run(api, make_org):
    member = await make_org("Org M", role="member")
    response = await api.post(f"{API}/agents/runs/000000000000000000000000/resume", headers=member["headers"], json={"approved": True})
    assert response.status_code == 403


async def test_a_member_may_still_cancel_a_paused_run(api, make_org):
    member = await make_org("Org M", role="member")
    response = await api.post(f"{API}/agents/runs/000000000000000000000000/resume", headers=member["headers"], json={"approved": False})
    assert response.status_code == 404  # reaches the lookup: cancelling is not role-restricted


async def test_a_member_cannot_approve_a_purchase_order_or_an_email(api, make_org):
    member = await make_org("Org M", role="member")
    for path in ("purchase-orders/000000000000000000000000/approve",
                 "communications/000000000000000000000000/approve"):
        response = await api.post(f"{API}/{path}", headers=member["headers"])
        assert response.status_code == 403, path
