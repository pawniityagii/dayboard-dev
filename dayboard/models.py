"""Core data models for Dayboard.

These are the shapes every part of the system agrees on. The data providers
(seed or real Gmail/Calendar) produce these; the agent consumes them; the web
layer renders them. Keeping one set of models is what lets demo mode and real
mode share the exact same agent code.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional


class Priority(str, Enum):
    URGENT = "urgent"
    NORMAL = "normal"
    LOW = "low"


class ItemKind(str, Enum):
    NEEDS_REPLY = "needs_reply"
    FYI = "fyi"
    MEETING = "meeting"


@dataclass
class Email:
    """A single email as the agent sees it. Source-agnostic: the seed provider
    and the Gmail provider both emit this shape."""
    id: str
    sender: str
    sender_email: str
    subject: str
    body: str
    received_at: datetime
    is_unread: bool = True
    thread_id: Optional[str] = None


@dataclass
class CalendarEvent:
    id: str
    title: str
    start: datetime
    end: datetime
    attendees: list[str] = field(default_factory=list)
    location: Optional[str] = None
    all_day: bool = False   # all-day events are shown but skipped in conflict detection


@dataclass
class BriefItem:
    """One line in the morning brief after the agent has reasoned over it."""
    kind: ItemKind
    priority: Priority
    title: str            # short headline shown in the list
    detail: str           # one-line explanation of why it matters
    source_id: str        # the email or event id this came from
    draft_reply: Optional[str] = None   # populated only for needs_reply items

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["priority"] = self.priority.value
        return d


@dataclass
class Conflict:
    """Two calendar events that overlap in time."""
    event_a: str
    event_b: str
    overlap_start: datetime
    overlap_end: datetime


@dataclass
class Brief:
    """The whole morning brief. This is what the dashboard renders and what the
    scheduled job would email."""
    generated_at: datetime
    summary: str
    items: list[BriefItem] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    mode: str = "demo"    # "demo" or "live" - shown in the UI for honesty

    @property
    def needs_reply(self) -> list[BriefItem]:
        return [i for i in self.items if i.kind == ItemKind.NEEDS_REPLY]

    @property
    def meetings(self) -> list[BriefItem]:
        return [i for i in self.items if i.kind == ItemKind.MEETING]

    @property
    def fyi(self) -> list[BriefItem]:
        return [i for i in self.items if i.kind == ItemKind.FYI]
