"""LLM council: several models answer, read each other's answers, then a monitor decides.

    round 1  answer    every member answers the question on its own
    round 2  review    every member reads the others' answers (anonymously) and revises
    round 3  decision  the monitor reads all revised answers and writes the final one

It is an AIProvider, so any task that calls generate() - explanations, the critic,
drafting - can be handed to a council by configuration alone. Anonymity is deliberate:
a member that knows which model wrote an answer tends to defer to the famous one.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from app.integrations.ai.base import AIProvider, AIResponse, ChatMessage, ChatResult

REVIEW_INSTRUCTION = (
    "Other council members answered the same question. Their answers are below, labelled only by letter.\n"
    "Point out anything they got right that you missed, or anything wrong in them, then give your own "
    "revised final answer in the same format the question asked for."
)
DECISION_INSTRUCTION = (
    "You chair a council of models. Each member answered the question below, read the others' answers "
    "and revised. Weigh the revised answers, prefer what most members support, drop anything only one "
    "member claimed without evidence, and write the single final answer in the format the question asked for."
)


class CouncilProvider(AIProvider):
    name = "council"
    supports_tools = False  # tool loops stay on single models; see chat()

    def __init__(self, members: list[AIProvider], monitor: AIProvider):
        self.members, self.monitor = members, monitor
        self.model = f"council({len(members)})->{monitor.model}"

    def is_configured(self) -> bool:
        return self.monitor.is_configured() and sum(m.is_configured() for m in self.members) >= 2

    def configuration_error(self) -> Optional[str]:
        return None if self.is_configured() else "A council needs a monitor and at least two configured members."

    async def generate(self, prompt: str, *, system: Optional[str] = None, json_mode: bool = False,
                       temperature: float = 0.1, max_output_tokens: int = 8192) -> AIResponse:
        options = {"system": system, "json_mode": json_mode, "temperature": temperature,
                   "max_output_tokens": max_output_tokens}
        transcript: list[dict[str, Any]] = []
        dropped: list[str] = []

        # Round 1: independent answers.
        first = await asyncio.gather(*(m.generate(prompt, **options) for m in self.members))
        answers: list[tuple[AIProvider, str]] = []
        for member, response in zip(self.members, first):
            if response.ok and response.text.strip():
                answers.append((member, response.text))
                transcript.append({"round": "answer", "member": member.model, "text": response.text})
            else:
                dropped.append(f"{member.model}: {response.error or 'empty answer'}")
        if len(answers) < 2:
            return AIResponse(ok=False, provider=self.name, model=self.model, meta={"dropped": dropped},
                              error=f"The council needs at least two answers; got {len(answers)}. {'; '.join(dropped)}")

        # Round 2: each member reads the others - never its own, never their names - and revises.
        def peers(index: int) -> str:
            others = [text for j, (_, text) in enumerate(answers) if j != index]
            return "\n\n".join(f"Member {chr(65 + k)}:\n{text}" for k, text in enumerate(others))

        reviews = await asyncio.gather(*(
            member.generate(f"{prompt}\n\n{REVIEW_INSTRUCTION}\n\n{peers(i)}", **options)
            for i, (member, _) in enumerate(answers)))
        revised: list[str] = []
        for (member, original), response in zip(answers, reviews):
            text = response.text if response.ok and response.text.strip() else original  # keep round 1 if review failed
            revised.append(text)
            transcript.append({"round": "review", "member": member.model, "text": text})

        # Round 3: the monitor decides.
        board = "\n\n".join(f"Member {chr(65 + k)}:\n{text}" for k, text in enumerate(revised))
        decision = await self.monitor.generate(
            f"{DECISION_INSTRUCTION}\n\nQuestion:\n{prompt}\n\nRevised answers:\n{board}", **options)
        if not decision.ok:
            return AIResponse(ok=False, provider=self.name, model=self.model, meta={"transcript": transcript,
                              "dropped": dropped}, error=f"The council monitor failed: {decision.error}")
        transcript.append({"round": "decision", "member": self.monitor.model, "text": decision.text})
        return AIResponse(text=decision.text, ok=True, provider=self.name, model=self.model,
                          meta={"transcript": transcript, "dropped": dropped})

    async def chat(self, messages: list[ChatMessage], *, tools: Optional[list[dict]] = None,
                   temperature: float = 0.2, max_output_tokens: int = 2048) -> ChatResult:
        # ponytail: tool-using conversations run on the monitor alone; a council per tool round
        # would multiply latency by ~7. Add council chat if a use case ever needs it.
        return await self.monitor.chat(messages, tools=tools, temperature=temperature,
                                       max_output_tokens=max_output_tokens)
