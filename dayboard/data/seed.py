"""Seed provider: a realistic fake inbox and calendar so the public demo works
with no login and no API keys. The data is deliberately mixed - genuine
reply-worthy mail, pure noise, and a calendar with one real time conflict - so
the agent has actual judgement to exercise and the demo shows it working."""
from __future__ import annotations

from datetime import datetime, timedelta

from ..models import Email, CalendarEvent
from .provider import DataProvider


def _today_at(hour: int, minute: int = 0) -> datetime:
    now = datetime.now()
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


class SeedProvider(DataProvider):
    """Fixed sample data. Times are relative to 'today' so the demo always looks
    current no matter when it is opened."""

    @property
    def mode(self) -> str:
        return "demo"

    def get_emails(self) -> list[Email]:
        now = datetime.now()
        return [
            Email(
                id="e1",
                sender="Priya Nair",
                sender_email="priya@brightwork.io",
                subject="Need the revised proposal by 2pm today",
                body=(
                    "Hi, the client moved the review call to this afternoon. "
                    "Can you send the revised proposal with the updated pricing "
                    "before 2pm? I'll need 30 minutes to go through it first."
                ),
                received_at=now - timedelta(hours=1),
            ),
            Email(
                id="e2",
                sender="AWS Billing",
                sender_email="no-reply@amazon.com",
                subject="Your AWS invoice is available",
                body="Your invoice for the billing period is now available in the console.",
                received_at=now - timedelta(hours=2),
            ),
            Email(
                id="e3",
                sender="Rahul Mehta",
                sender_email="rahul@brightwork.io",
                subject="Re: onboarding docs - one blocker",
                body=(
                    "The new hire can't access the shared drive. Can you approve "
                    "her access request today so she's unblocked before she starts "
                    "Monday? Link is in the earlier thread."
                ),
                received_at=now - timedelta(hours=3),
            ),
            Email(
                id="e4",
                sender="LinkedIn",
                sender_email="notifications@linkedin.com",
                subject="You appeared in 9 searches this week",
                body="See who's been looking at your profile. Upgrade to Premium to see more.",
                received_at=now - timedelta(hours=4),
            ),
            Email(
                id="e5",
                sender="Dr. Sharma's Clinic",
                sender_email="appointments@sharmaclinic.in",
                subject="Appointment reminder - Thursday 5:30pm",
                body="This is a reminder of your appointment on Thursday at 5:30pm. Reply CONFIRM to confirm.",
                received_at=now - timedelta(hours=5),
            ),
            Email(
                id="e6",
                sender="Ananya (Design)",
                sender_email="ananya@brightwork.io",
                subject="Quick q on the dashboard colours",
                body=(
                    "Are we locked on the dark theme for the launch, or should I "
                    "prep a light variant too? Need to know before I hand off to dev."
                ),
                received_at=now - timedelta(hours=6),
            ),
            Email(
                id="e7",
                sender="Zomato",
                sender_email="noreply@zomato.com",
                subject="Craving something? 60% off today only",
                body="Order now and get 60% off your first order of the day.",
                received_at=now - timedelta(hours=7),
            ),
        ]

    def get_events(self) -> list[CalendarEvent]:
        return [
            CalendarEvent(
                id="c1",
                title="Team standup",
                start=_today_at(9, 30),
                end=_today_at(9, 45),
                attendees=["team@brightwork.io"],
            ),
            CalendarEvent(
                id="c2",
                title="Client proposal review",
                start=_today_at(14, 0),
                end=_today_at(15, 0),
                attendees=["priya@brightwork.io", "client@acme.com"],
                location="Zoom",
            ),
            # c3 overlaps c2 on purpose - the agent should catch this conflict.
            CalendarEvent(
                id="c3",
                title="1:1 with Rahul",
                start=_today_at(14, 30),
                end=_today_at(15, 0),
                attendees=["rahul@brightwork.io"],
            ),
            CalendarEvent(
                id="c4",
                title="Focus block: proposal edits",
                start=_today_at(11, 0),
                end=_today_at(12, 30),
                attendees=[],
            ),
        ]
