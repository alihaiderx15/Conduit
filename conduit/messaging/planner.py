"""AI routing for natural-language messaging requests."""
from __future__ import annotations
import json
import re

from conduit.core.models import ChatMessage, Role
from .models import MessagingPlan

_ALLOWED = {
    "messaging.send",
    "messaging.open_chat",
    "messaging.read_recent",
    "messaging.resolve_contact",
}
_SERVICES = ("whatsapp", "telegram", "discord")


class AIMessagingRouter:
    def __init__(self, provider, *, model: str) -> None:
        self.provider = provider
        self.model = model

    async def plan(self, request: str, *, history: str = "") -> MessagingPlan | None:
        prompt = f"""You are Conduit's messaging intent router.
Return ONLY JSON or null.

Supported actions:
- messaging.send: user wants a message sent to another person.
- messaging.open_chat: user wants a person's chat opened.
- messaging.read_recent: user wants recent messages from a specific chat read/summarized.
- messaging.resolve_contact: user wants a recipient/contact found.

Supported services right now: WhatsApp, Telegram, and Discord.

For messaging.send return:
{{
 "action":"messaging.send",
 "service":"whatsapp|telegram|discord",
 "recipient":"person/contact exactly as user described",
 "message":"exact message ONLY when the user clearly wants those literal words sent unchanged AND did not request writing, rewriting, tone, style, or format",
 "compose_instruction":"the complete meaning, facts, requested tone/style/format, and writing instruction whenever Conduit should use its AI brain to draft the message; otherwise empty"
}}

CRITICAL COMPOSITION RULE:
If the user asks for ANY transformation or writing style -- professional, formal, polite,
friendly, funny, humorous, casual, respectful, application-style, email/mail-style,
letter-style, paragraph form, reworded, improved, rewritten, or similar -- NEVER put
the raw content in "message". Set "message" to empty and put the full instruction in
"compose_instruction". The AI composer must write the final wording.

Examples of semantics:
"send Ali on whatsapp: I'll be there at 6" => exact message "I'll be there at 6".
"tell my boss on whatsapp I'm sick and make it professional" => message empty; compose_instruction says to professionally explain that the user is ill.
"message Maryam that I am ill and cannot come tomorrow, make it professional" => message empty; compose_instruction preserves both facts and requests a polished professional paragraph.
"tell Ali I cannot attend tomorrow, make it funny" => message empty; compose_instruction preserves the absence fact and requests light humorous wording.
"send my teacher an application-type message saying I am ill and cannot come tomorrow" => message empty; compose_instruction requests a respectful application-style message.
"open the chat of Maryam in whatsapp and message Hi" => messaging.send, recipient "Maryam", exact message "Hi".
"open chat with Basit and message him Hello" => messaging.send, using the active messaging service from context when available.

IMPORTANT: if a request both opens/selects a chat AND asks to message/text/send something, the action is messaging.send, not messaging.open_chat.
Never invent a recipient or service. If service is absent and no active messaging service exists in context, return null so Conduit can ask naturally.
Do not send anything yourself.

Conversation context:
{history}

Current request:
{request}
"""
        specialist = getattr(self.provider, "specialist_chat", self.provider.chat)
        response = await specialist(
            [ChatMessage(Role.USER, prompt)],
            model=self.model,
        )
        raw = response.text.strip()
        if raw.casefold() == "null":
            return None
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            return None
        data = json.loads(match.group(0))
        action = str(data.get("action", "")).strip()
        service = str(data.get("service", "")).casefold().strip()
        if action not in _ALLOWED or service not in _SERVICES:
            return None
        return MessagingPlan(
            action=action,
            service=service,
            recipient=str(data.get("recipient", "")).strip(),
            message=str(data.get("message", "")).strip(),
            compose_instruction=str(data.get("compose_instruction", "")).strip(),
            count=max(1, min(int(data.get("count", 5) or 5), 20)),
        )
