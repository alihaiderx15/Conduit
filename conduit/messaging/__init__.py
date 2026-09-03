"""Structured messaging capability."""
from .models import MessagingPlan, MessagingClient, ContactCandidate
from .planner import AIMessagingRouter
from .service import SERVICE_CONFIG, ensure_visible_client, observe_messaging_screen
__all__ = [
    "MessagingPlan", "MessagingClient", "ContactCandidate",
    "AIMessagingRouter", "SERVICE_CONFIG", "ensure_visible_client",
    "observe_messaging_screen",
]
