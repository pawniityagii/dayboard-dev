"""The Dayboard agent.

Pipeline: fetch -> triage emails -> draft replies -> detect calendar conflicts
-> extract action items -> write a summary -> assemble the Brief.

Each step tries the LLM first and falls back to rules.py if no LLM is configured
or the call fails. That means the public demo runs with zero keys, and the same
code produces real AI reasoning the moment a GEMINI_API_KEY is present.
"""
from __future__ import annotations

import json
from datetime import datetime
from itertools import combinations

from ..models import (
    Brief, BriefItem, CalendarEvent, Conflict, Email, ItemKind, Priority,
)
from ..data.provider import DataProvider
from . import llm, rules, voice


# ---------- email triage ----------

def _triage_with_llm(emails: list[Email]) -> list[BriefItem]:
    listing = "\n".join(
        f'[{e.id}] From: {e.sender} <{e.sender_email}>\n'
        f'    Subject: {e.subject}\n    Body: {e.body}'
        for e in emails
    )
    prompt = (
        "You are an executive assistant triaging a morning inbox. For each email, "
        "decide: does it genuinely need a reply from the recipient, is it just FYI, "
        "or is it noise/promotional? Assign a priority: urgent, normal, or low.\n\n"
        "Return ONLY a JSON array, one object per email, with keys: "
        'id, kind (one of "needs_reply", "fyi"), priority (one of "urgent", '
        '"normal", "low"), reason (one short sentence on why).\n\n'
        f"Emails:\n{listing}"
    )
    data = llm.complete_json(prompt)
    by_id = {e.id: e for e in emails}
    items: list[BriefItem] = []
    for row in data:
        e = by_id.get(row["id"])
        if not e:
            continue
        kind = ItemKind(row["kind"])
        items.append(BriefItem(
            kind=kind,
            priority=Priority(row["priority"]),
            title=f"{e.sender}: {e.subject}",
            detail=row.get("reason", ""),
            source_id=e.id,
        ))
    return items


def _triage_with_rules(emails: list[Email]) -> list[BriefItem]:
    items: list[BriefItem] = []
    for e in emails:
        kind, priority = rules.classify_email(e)
        detail = {
            ItemKind.NEEDS_REPLY: "Looks like the sender is waiting on a response.",
            ItemKind.FYI: "No action needed - informational.",
        }[kind]
        items.append(BriefItem(
            kind=kind, priority=priority,
            title=f"{e.sender}: {e.subject}", detail=detail, source_id=e.id,
        ))
    return items


# ---------- reply drafting ----------

def _draft_with_llm(email: Email) -> str:
    profile = voice.guidance()
    if profile:
        voice_block = (
            "\n\nWrite in this person's own voice. Here is how they write - "
            "mirror their tone, greeting, sign-off and sentence length:\n"
            f"{profile}\n"
        )
        sign = "Use the sign-off shown in their voice profile."
    else:
        voice_block = ""
        sign = "Sign off as Pawni."
    prompt = (
        "Write a brief reply to this email. Keep it concise, 2-4 sentences. "
        "Do not invent specifics or commit to anything concrete - acknowledge "
        f"and give a realistic next step. {sign} Return only the reply text."
        f"{voice_block}\n"
        f"From: {email.sender}\nSubject: {email.subject}\nBody: {email.body}"
    )
    return llm.complete(prompt, temperature=0.4).strip()


# ---------- calendar conflicts ----------

def _detect_conflicts(events: list[CalendarEvent]) -> list[Conflict]:
    conflicts: list[Conflict] = []
    # All-day events (OOO, holidays) span the whole day and would otherwise
    # "overlap" every meeting; they are not real scheduling conflicts.
    timed = [e for e in events if not e.all_day]
    for a, b in combinations(timed, 2):
        start = max(a.start, b.start)
        end = min(a.end, b.end)
        if start < end:
            conflicts.append(Conflict(
                event_a=a.title, event_b=b.title,
                overlap_start=start, overlap_end=end,
            ))
    return conflicts


# ---------- summary ----------

def _summary_with_llm(items: list[BriefItem], events: list[CalendarEvent],
                      conflicts: list[Conflict]) -> str:
    reply_count = sum(1 for i in items if i.kind == ItemKind.NEEDS_REPLY)
    prompt = (
        "Write a single friendly sentence summarising someone's day for a morning "
        "brief. Mention how many emails need a reply and how many meetings they "
        "have. Mention if there is a scheduling conflict. Keep it under 30 words.\n\n"
        f"Emails needing reply: {reply_count}\n"
        f"Meetings today: {len(events)}\n"
        f"Conflicts: {len(conflicts)}"
    )
    return llm.complete(prompt, temperature=0.5).strip()


def _summary_with_rules(items: list[BriefItem], events: list[CalendarEvent],
                        conflicts: list[Conflict]) -> str:
    reply_count = sum(1 for i in items if i.kind == ItemKind.NEEDS_REPLY)
    parts = [f"You have {reply_count} email{'s' if reply_count != 1 else ''} that "
             f"need a reply and {len(events)} meeting{'s' if len(events) != 1 else ''} today"]
    if conflicts:
        parts.append(f"heads up: {len(conflicts)} scheduling conflict to resolve")
    return ", ".join(parts) + "."


# ---------- orchestration ----------

def build_brief(provider: DataProvider) -> Brief:
    emails = provider.get_emails()
    events = provider.get_events()
    use_llm = llm.is_configured()

    # 1. triage
    if use_llm:
        try:
            items = _triage_with_llm(emails)
        except llm.LLMUnavailable:
            items = _triage_with_rules(emails)
    else:
        items = _triage_with_rules(emails)

    # 2. draft replies for needs_reply items
    by_id = {e.id: e for e in emails}
    for item in items:
        if item.kind == ItemKind.NEEDS_REPLY:
            email = by_id[item.source_id]
            if use_llm:
                try:
                    item.draft_reply = _draft_with_llm(email)
                except llm.LLMUnavailable:
                    item.draft_reply = rules.draft_reply(email)
            else:
                item.draft_reply = rules.draft_reply(email)

    # 3. meetings become brief items too, in chronological order
    for ev in sorted(events, key=lambda e: e.start):
        when = "All day" if ev.all_day else ev.start.strftime("%-I:%M %p")
        items.append(BriefItem(
            kind=ItemKind.MEETING, priority=Priority.NORMAL,
            title=f"{when} - {ev.title}",
            detail=(f"with {', '.join(ev.attendees)}" if ev.attendees else "solo block")
                   + (f" ({ev.location})" if ev.location else ""),
            source_id=ev.id,
        ))

    # 4. conflicts
    conflicts = _detect_conflicts(events)

    # 5. action items
    action_items = rules.extract_action_items(emails)

    # 6. summary
    if use_llm:
        try:
            summary = _summary_with_llm(items, events, conflicts)
        except llm.LLMUnavailable:
            summary = _summary_with_rules(items, events, conflicts)
    else:
        summary = _summary_with_rules(items, events, conflicts)

    # order: urgent first, then by kind
    priority_rank = {Priority.URGENT: 0, Priority.NORMAL: 1, Priority.LOW: 2}
    items.sort(key=lambda i: (priority_rank[i.priority], i.kind.value))

    return Brief(
        generated_at=datetime.now(),
        summary=summary,
        items=items,
        conflicts=conflicts,
        action_items=action_items,
        # data-source axis: demo = sample inbox, live = real Google account.
        # AI-vs-rules is a separate axis surfaced via llm.is_configured() in app.py.
        mode=provider.mode,
    )
