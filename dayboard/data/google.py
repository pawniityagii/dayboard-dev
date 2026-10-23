"""Real Gmail + Google Calendar provider (Phase 2).

Implements the same DataProvider interface as SeedProvider. When a user has
connected their Google account, app.py builds one of these with their
credentials and hands it to the agent instead of SeedProvider - and nothing
else in the system changes. The agent, the brief, and the UI are identical;
only the source of the Email/CalendarEvent objects differs.

The Google client libraries are imported lazily inside the methods so that demo
mode still runs when the Phase 2 dependencies are not installed.
"""
from __future__ import annotations

import base64
from email.message import EmailMessage
from datetime import datetime, timedelta
from email.utils import parseaddr

from ..models import Email, CalendarEvent
from .provider import DataProvider

# How much inbox to pull. Matches the "morning brief" framing: unread, last day.
_GMAIL_QUERY = "is:unread newer_than:1d"
_GMAIL_MAX = 20


def _header(headers, name):
    """Pull a header value by name (case-insensitive) from Gmail's header list."""
    name = name.lower()
    for h in headers or []:
        if h.get("name", "").lower() == name:
            return h.get("value", "")
    return ""


def _b64url(data):
    """Decode Gmail's base64url body data to text, tolerating missing padding."""
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _strip_html(markup):
    """Very small HTML-to-text: drop script/style, drop tags, decode entities,
    collapse whitespace. Good enough for triage - the agent reads meaning, not
    markup. Real HTML mail is full of entities (&nbsp;, &amp;, &#39;), so they
    are unescaped rather than left as literal text."""
    import re
    import html as _html
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", markup)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_body(payload):
    """Walk a (possibly multipart) Gmail payload and return the best body text.
    Prefers text/plain; falls back to text/html stripped of tags."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {}) or {}

    if mime == "text/plain":
        return _b64url(body.get("data", ""))
    if mime == "text/html":
        return _strip_html(_b64url(body.get("data", "")))

    # multipart/*: prefer a plain part, then an html part, then recurse.
    parts = payload.get("parts", []) or []
    for part in parts:
        if part.get("mimeType") == "text/plain":
            text = _b64url(part.get("body", {}).get("data", ""))
            if text:
                return text
    for part in parts:
        if part.get("mimeType") == "text/html":
            text = _strip_html(_b64url(part.get("body", {}).get("data", "")))
            if text:
                return text
    for part in parts:
        text = _extract_body(part)
        if text:
            return text
    return ""


def _reply_subject(subject: str) -> str:
    """Prefix 'Re: ' unless the subject already carries one."""
    subject = (subject or "").strip()
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}" if subject else "Re:"


def _to_naive_local(dt):
    """Convert an aware datetime to naive local time, matching the seed
    provider's naive datetimes so conflict detection and the UI's strftime
    behave identically across modes."""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


class GoogleProvider(DataProvider):
    """Live data from the signed-in user's Gmail and primary calendar."""

    def __init__(self, credentials):
        # credentials: an authorised google.oauth2.credentials.Credentials
        self._creds = credentials

    @property
    def mode(self) -> str:
        return "live"

    def _service(self, api, version):
        from googleapiclient.discovery import build
        return build(api, version, credentials=self._creds, cache_discovery=False)

    def get_emails(self) -> list[Email]:
        service = self._service("gmail", "v1")
        listing = service.users().messages().list(
            userId="me", q=_GMAIL_QUERY, maxResults=_GMAIL_MAX
        ).execute()

        emails: list[Email] = []
        for ref in listing.get("messages", []):
            msg = service.users().messages().get(
                userId="me", id=ref["id"], format="full"
            ).execute()

            payload = msg.get("payload", {})
            headers = payload.get("headers", [])
            from_raw = _header(headers, "From")
            name, addr = parseaddr(from_raw)

            received = datetime.now()
            internal = msg.get("internalDate")
            if internal:
                # internalDate is epoch milliseconds (UTC) -> naive local.
                received = _to_naive_local(
                    datetime.fromtimestamp(int(internal) / 1000).astimezone()
                )

            label_ids = msg.get("labelIds", []) or []
            body = _extract_body(payload) or msg.get("snippet", "")

            emails.append(Email(
                id=msg.get("id", ref["id"]),
                sender=name or addr or "(unknown sender)",
                sender_email=addr,
                subject=_header(headers, "Subject") or "(no subject)",
                body=body.strip(),
                received_at=received,
                is_unread="UNREAD" in label_ids,
                thread_id=msg.get("threadId"),
            ))
        return emails

    def get_events(self) -> list[CalendarEvent]:
        from dateutil import parser as date_parser

        service = self._service("calendar", "v3")

        now_local = datetime.now().astimezone()
        start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        resp = service.events().list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events: list[CalendarEvent] = []
        for ev in resp.get("items", []):
            start_info = ev.get("start", {})
            end_info = ev.get("end", {})

            # Timed events carry dateTime; all-day events carry date only.
            start_raw = start_info.get("dateTime") or start_info.get("date")
            end_raw = end_info.get("dateTime") or end_info.get("date")
            if not start_raw or not end_raw:
                continue

            start_dt = _to_naive_local(date_parser.isoparse(start_raw))
            end_dt = _to_naive_local(date_parser.isoparse(end_raw))
            # all-day events carry "date" (no "dateTime"); flag so they don't
            # trip the conflict detector against every timed meeting.
            all_day = "dateTime" not in start_info

            attendees = [
                a.get("email") for a in ev.get("attendees", []) or []
                if a.get("email") and not a.get("self")
            ]

            events.append(CalendarEvent(
                id=ev.get("id", ""),
                title=ev.get("summary", "(no title)"),
                start=start_dt,
                end=end_dt,
                attendees=attendees,
                location=ev.get("location"),
                all_day=all_day,
            ))
        return events

    def send_reply(self, email_id: str, body_text: str) -> dict:
        """Send an approved reply to the message with id email_id.

        Looks up the original to address the reply correctly and thread it
        (To from Reply-To/From, a 'Re:' subject, In-Reply-To/References headers,
        same Gmail thread). Returns {"to", "subject", "id"} on success. Requires
        the gmail.send scope. Raises ValueError if the text is empty or the
        recipient cannot be determined; Google API errors propagate to the
        caller, which turns them into a message in the UI."""
        body_text = (body_text or "").strip()
        if not body_text:
            raise ValueError("reply text is empty")

        service = self._service("gmail", "v1")
        original = service.users().messages().get(
            userId="me", id=email_id, format="metadata",
            metadataHeaders=["From", "Reply-To", "Subject", "Message-ID"],
        ).execute()

        headers = original.get("payload", {}).get("headers", [])
        reply_to = _header(headers, "Reply-To")
        from_hdr = _header(headers, "From")
        _, recipient = parseaddr(reply_to or from_hdr)
        if not recipient:
            raise ValueError("could not determine a recipient for the reply")

        message_id = _header(headers, "Message-ID")
        thread_id = original.get("threadId")

        msg = EmailMessage()
        msg["To"] = recipient
        msg["Subject"] = _reply_subject(_header(headers, "Subject"))
        if message_id:
            # Proper threading so the reply lands in the same conversation.
            msg["In-Reply-To"] = message_id
            msg["References"] = message_id
        msg.set_content(body_text)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id
        sent = service.users().messages().send(userId="me", body=payload).execute()

        return {"to": recipient, "subject": msg["Subject"], "id": sent.get("id")}

