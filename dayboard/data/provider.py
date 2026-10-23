"""Data providers. A provider answers two questions: what's in the inbox, and
what's on the calendar today. Everything downstream is identical regardless of
which provider is used, which is the whole point of this interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Email, CalendarEvent


class DataProvider(ABC):
    @abstractmethod
    def get_emails(self) -> list[Email]:
        ...

    @abstractmethod
    def get_events(self) -> list[CalendarEvent]:
        ...

    @property
    @abstractmethod
    def mode(self) -> str:
        ...
