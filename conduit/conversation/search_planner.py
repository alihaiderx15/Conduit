"""AI-powered search intent normalization for conversational web requests."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from conduit.core.models import ChatMessage, Role


_WEB_ACTIONS = {
    "web.search",
    "web.news",
    "web.research",
    "web.price_search",
    "web.compare",
}


@dataclass(frozen=True, slots=True)
class SearchPlan:
    """A normalized web task produced by the active AI model."""

    action: str
    arguments: dict[str, Any]
    intent: str = ""
    subject: str = ""
    rewritten_request: str = ""
    answer_style: str = "concise"
    sources_requested: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)
    query_variants: tuple[str, ...] = field(default_factory=tuple)
    exclude_terms: tuple[str, ...] = field(default_factory=tuple)
    source_preferences: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "arguments": dict(self.arguments),
            "intent": self.intent,
            "subject": self.subject,
            "rewritten_request": self.rewritten_request,
            "answer_style": self.answer_style,
            "sources_requested": self.sources_requested,
            "notes": list(self.notes),
            "query_variants": list(self.query_variants),
            "exclude_terms": list(self.exclude_terms),
            "source_preferences": list(self.source_preferences),
        }


class AISearchPlanner:
    """Use the active model to turn messy user language into a clean web plan."""

    def __init__(self, provider, model: str) -> None:
        self.provider = provider
        self.model = model

    async def plan(
        self,
        user_message: str,
        *,
        recent_context: str = "",
        allowed_actions: set[str] | None = None,
        evidence_hypothesis: str = "",
    ) -> SearchPlan:
        allowed = sorted((allowed_actions or _WEB_ACTIONS) & _WEB_ACTIONS)
        if not allowed:
            allowed = sorted(_WEB_ACTIONS)

        context_block = (
            "\nREFERENCE CONTEXT (use only to resolve explicit pronouns/references):\n"
            + recent_context
            if recent_context.strip()
            else ""
        )
        hypothesis_block = (
            "\nMODEL HYPOTHESIS TO VERIFY (not trusted evidence):\n"
            + evidence_hypothesis
            + "\nUse this only to generate targeted verification queries for likely "
              "entities/claims. The web evidence may correct it. Do not assume it is true.\n"
            if evidence_hypothesis.strip()
            else ""
        )
        prompt = f"""You are Conduit's SEARCH PLANNER. You do not answer the user.
Convert the CURRENT user message into the best structured web request.

Your job:
- Correct spelling mistakes, typos, slang, and shorthand.
- Preserve the user's real meaning; never replace the topic with an older topic.
- Disambiguate ambiguous entities from context. Example: "Python news" in a programming conversation means the Python programming language, not snakes.
- Add useful search wording such as country, currency, subject category, freshness, or evidence type when the user clearly implies them.
- Prefer academic/review wording when the user asks for studies, research, papers, or evidence.
- For current weather, create multiple specific queries including exact location + weather + current conditions/temperature.
- For ambiguous entities, explicitly disambiguate and add exclusions. Example: Python programming news should exclude snake/reptile meanings.
- Generate 2-5 useful query variants instead of relying on one phrase.
- When a MODEL HYPOTHESIS TO VERIFY is provided, target its concrete candidate
  entities/claims with verification queries instead of searching only the broad
  wording of the user's question.
- For ranking/list questions, search for the actual ranking/statistic and, when
  useful, candidate-specific record queries. A generic homepage is not evidence
  for a ranking.
- For research/studies, prefer primary studies, systematic reviews, universities, journals, government or recognized medical sources rather than generic homepages.
- For product prices, extract only the product into `item`, and put market/country in `region` and currency in `currency` when known.
- For comparisons, identify the compared items and user criteria.
- Do not invent facts or answer the question.

Allowed actions: {json.dumps(allowed)}

ACTION ARGUMENT SCHEMAS:
web.search -> {{"query": string, "query_variants": [string], "exclude_terms": [string], "limit": integer, "use_grounding": boolean, "region": string}}
web.news -> {{"query": string, "query_variants": [string], "exclude_terms": [string], "limit": integer, "parallel_queries": integer}}
web.research -> {{"query": string, "query_variants": [string], "exclude_terms": [string], "source_preferences": [string], "depth": integer, "sources_per_query": integer, "use_grounding": boolean}}
web.price_search -> {{"item": string, "region": string, "currency": string, "query_variants": [string], "exclude_terms": [string], "limit": integer}}
web.compare -> {{"items": [string, ...], "criteria": [string, ...], "region": string, "include_prices": boolean}}

Return ONLY one JSON object with exactly these top-level fields:
{{
  "action": "one allowed action",
  "arguments": {{...}},
  "intent": "short intent label",
  "subject": "normalized subject/entity",
  "rewritten_request": "clean natural-language version of what should be searched",
  "answer_style": "concise" or "detailed",
  "sources_requested": true or false,
  "query_variants": ["2-5 optimized search queries that preserve the same intent"],
  "exclude_terms": ["terms/meanings that would cause ambiguity or irrelevant results"],
  "source_preferences": ["preferred source types, e.g. official, academic, medical, local retailer"],
  "notes": ["optional disambiguation notes"]
}}

Use `detailed` only when the user explicitly asks for detail, full breakdown, exhaustive explanation, report, or step-by-step depth. Otherwise use `concise`.
{context_block}
{hypothesis_block}

CURRENT USER MESSAGE:
{user_message}
"""
        response = await self.provider.chat(
            [ChatMessage(Role.USER, prompt)],
            model=self.model,
        )
        raw = _parse_json_object(response.text)
        return _normalize_plan(raw, allowed, user_message)


def _parse_json_object(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        value = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.S)
        if not match:
            raise ValueError("Search planner did not return a JSON object.")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Search planner response must be a JSON object.")
    return value


def _normalize_plan(
    raw: dict[str, Any],
    allowed: list[str],
    original: str,
) -> SearchPlan:
    action = str(raw.get("action", "")).strip()
    if action not in allowed:
        action = allowed[0]

    arguments = raw.get("arguments", {})
    if not isinstance(arguments, dict):
        arguments = {}
    args = dict(arguments)

    raw_variants = raw.get("query_variants", args.get("query_variants", []))
    if not isinstance(raw_variants, list):
        raw_variants = []
    query_variants = tuple(
        str(item).strip()
        for item in raw_variants
        if str(item).strip()
    )[:5]

    raw_exclusions = raw.get("exclude_terms", args.get("exclude_terms", []))
    if not isinstance(raw_exclusions, list):
        raw_exclusions = []
    exclude_terms = tuple(
        str(item).strip()
        for item in raw_exclusions
        if str(item).strip()
    )[:10]

    raw_preferences = raw.get("source_preferences", args.get("source_preferences", []))
    if not isinstance(raw_preferences, list):
        raw_preferences = []
    source_preferences = tuple(
        str(item).strip()
        for item in raw_preferences
        if str(item).strip()
    )[:10]

    # Keep only valid arguments and fill conservative defaults.
    if action == "web.search":
        args = {
            "query": str(args.get("query") or raw.get("rewritten_request") or original).strip(),
            "limit": _bounded_int(args.get("limit"), 8, 1, 20),
            "use_grounding": bool(args.get("use_grounding", True)),
            "region": str(args.get("region", "wt-wt")),
            "query_variants": list(query_variants),
            "exclude_terms": list(exclude_terms),
        }
    elif action == "web.news":
        args = {
            "query": str(args.get("query") or raw.get("rewritten_request") or original).strip(),
            "limit": _bounded_int(args.get("limit"), 12, 1, 30),
            "parallel_queries": _bounded_int(args.get("parallel_queries"), 3, 1, 5),
            "query_variants": list(query_variants),
            "exclude_terms": list(exclude_terms),
        }
    elif action == "web.research":
        args = {
            "query": str(args.get("query") or raw.get("rewritten_request") or original).strip(),
            "depth": _bounded_int(args.get("depth"), 2, 1, 3),
            "sources_per_query": _bounded_int(args.get("sources_per_query"), 5, 2, 10),
            "use_grounding": bool(args.get("use_grounding", True)),
            "query_variants": list(query_variants),
            "exclude_terms": list(exclude_terms),
            "source_preferences": list(source_preferences),
        }
    elif action == "web.price_search":
        args = {
            "item": str(args.get("item") or raw.get("subject") or original).strip(),
            "region": str(args.get("region", "")).strip(),
            "currency": str(args.get("currency", "")).strip(),
            "limit": _bounded_int(args.get("limit"), 10, 1, 20),
            "query_variants": list(query_variants),
            "exclude_terms": list(exclude_terms),
        }
    elif action == "web.compare":
        items = args.get("items", [])
        if not isinstance(items, list):
            items = []
        criteria = args.get("criteria", [])
        if not isinstance(criteria, list):
            criteria = []
        args = {
            "items": [str(item).strip() for item in items if str(item).strip()][:6],
            "criteria": [str(item).strip() for item in criteria if str(item).strip()][:8],
            "region": str(args.get("region", "")).strip(),
            "include_prices": bool(args.get("include_prices", True)),
        }

    style = str(raw.get("answer_style", "concise")).casefold()
    if style not in {"concise", "detailed"}:
        style = "concise"
    notes = raw.get("notes", [])
    if not isinstance(notes, list):
        notes = []

    return SearchPlan(
        action=action,
        arguments=args,
        intent=str(raw.get("intent", "")).strip(),
        subject=str(raw.get("subject", "")).strip(),
        rewritten_request=str(raw.get("rewritten_request", original)).strip(),
        answer_style=style,
        sources_requested=bool(raw.get("sources_requested", False)),
        notes=tuple(str(item) for item in notes[:8]),
        query_variants=query_variants,
        exclude_terms=exclude_terms,
        source_preferences=source_preferences,
    )


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))

@dataclass(frozen=True, slots=True)
class IntentPlan:
    """High-level conversation route chosen by the active model."""

    route: str
    web_needed: bool
    browser_requested: bool = False
    normalized_request: str = ""
    intent: str = ""


class AIIntentRouter:
    """Classify the user's current message before any tool selection happens."""

    def __init__(self, provider, model: str) -> None:
        self.provider = provider
        self.model = model

    async def plan(
        self,
        user_message: str,
        *,
        recent_context: str = "",
    ) -> IntentPlan:
        context_block = (
            "\nREFERENCE CONTEXT (only for explicit references in the current message):\n"
            + recent_context
            if recent_context.strip()
            else ""
        )
        prompt = f"""You are Conduit's CONVERSATION INTENT ROUTER.
Classify the CURRENT user message. Correct spelling/typos mentally before deciding.
Do not answer the user and do not let an older conversation topic replace a new self-contained topic.

Routing rules:
- `direct`: stable/general knowledge, explanation, normal recommendation, creative request, or comparison that does NOT require current information or sources.
- `tool`: the user wants a computer/browser/file action OR needs live web information such as current weather, current price, news, availability, research/studies, verification, or explicit sources.
- `hybrid`: the user wants a stable/general comparison or explanation AND also asks for live/current information or sources. The final answer should combine model knowledge with web evidence.
- `web_needed` is true only when live web retrieval/research is actually needed.
- `browser_requested` is true only when the user explicitly wants a visible browser opened/controlled. Saying "don't open a browser" means false.
- Understand misspellings, shorthand, slang, and typos such as `prcie`, `studys`, `sorces`, `rn`, etc.

Return ONLY JSON:
{{
  "route": "direct" | "tool" | "hybrid",
  "web_needed": true | false,
  "browser_requested": true | false,
  "normalized_request": "clean corrected version of the current request",
  "intent": "short generic intent label"
}}
{context_block}

CURRENT USER MESSAGE:
{user_message}
"""
        response = await self.provider.chat(
            [ChatMessage(Role.USER, prompt)],
            model=self.model,
        )
        raw = _parse_json_object(response.text)
        route = str(raw.get("route", "direct")).casefold()
        if route not in {"direct", "tool", "hybrid"}:
            route = "direct"
        return IntentPlan(
            route=route,
            web_needed=bool(raw.get("web_needed", False)),
            browser_requested=bool(raw.get("browser_requested", False)),
            normalized_request=str(raw.get("normalized_request", user_message)).strip(),
            intent=str(raw.get("intent", "")).strip(),
        )
