"""Deterministic fallback logic.

When no LLM is configured, the agent uses these rules so the demo still works,
costs nothing, and is predictable. This is intentionally simple heuristic logic,
not pretending to be AI - the real reasoning path is in agent.py via the LLM.
The two paths produce the same BriefItem shapes.
"""
from __future__ import annotations

from ..models import Email, Priority, ItemKind

# Senders/subjects that are almost always noise, not reply-worthy.
_NOISE_SENDERS = (
    "no-reply", "noreply", "notifications@linkedin", "notifications@",
    "@zomato", "@swiggy", "billing@", "@amazon.com",
)
_NOISE_SUBJECT_HINTS = ("off today", "% off", "appeared in", "invoice is available", "upgrade to premium")

# Words that suggest the sender wants something back from you.
_REPLY_HINTS = ("can you", "could you", "need the", "please", "approve", "let me know",
                "before", "by 2pm", "by today", "?", "blocker", "waiting on")
_URGENT_HINTS = ("today", "2pm", "asap", "urgent", "before monday", "eod", "by end of day")


def classify_email(email: Email) -> tuple[ItemKind, Priority]:
    sender = email.sender_email.lower()
    subject = email.subject.lower()
    body = email.body.lower()

    if any(n in sender for n in _NOISE_SENDERS) or any(h in subject for h in _NOISE_SUBJECT_HINTS):
        return ItemKind.FYI, Priority.LOW

    text = subject + " " + body
    wants_reply = any(h in text for h in _REPLY_HINTS)
    urgent = any(h in text for h in _URGENT_HINTS)

    if wants_reply:
        return ItemKind.NEEDS_REPLY, (Priority.URGENT if urgent else Priority.NORMAL)
    return ItemKind.FYI, (Priority.NORMAL if urgent else Priority.LOW)


def draft_reply(email: Email) -> str:
    """A plain, safe placeholder reply. The LLM path writes something better;
    this just proves the slot is wired and gives the demo something to show."""
    first_name = email.sender.split()[0]
    return (
        f"Hi {first_name},\n\n"
        "Thanks for the note - I've seen this and will get it to you shortly. "
        "Will follow up with specifics before the deadline.\n\n"
        "Best,\nPawni"
    )


def extract_action_items(emails: list[Email]) -> list[str]:
    items: list[str] = []
    for e in emails:
        kind, _ = classify_email(e)
        if kind == ItemKind.NEEDS_REPLY:
            items.append(f"Respond to {e.sender} about \"{e.subject}\"")
    return items
