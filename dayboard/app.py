"""FastAPI app. Serves the dashboard and a JSON API.

The data provider is chosen per request: if the user has connected their Google
account (a valid OAuth token in the session), Dayboard runs on their real Gmail
and Calendar - live mode. Otherwise it runs on the sample inbox - demo mode.
Either way the agent and the UI are the same code; only get_provider() differs.

Two independent switches decide what the user sees:
  - data source:  seed (demo)  vs  Google (live)   -> provider.mode
  - reasoning:    rules         vs  Gemini (AI)     -> llm.is_configured()
"""
from __future__ import annotations

import os
import secrets
from datetime import date

# Load a local .env (if present) so GOOGLE_CLIENT_ID, SESSION_SECRET, etc. don't
# have to be re-exported every session. No-op when the file or the library is
# absent, so it never breaks the demo or a platform that injects real env vars.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .agent.core import build_brief
from .agent import llm
from .data.seed import SeedProvider
from .data import google_auth

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))

app = FastAPI(title="Dayboard", description="Your AI chief of staff")

# Signed session cookie holds the OAuth token. Set SESSION_SECRET in production
# (Render) so sessions survive restarts; a random dev secret is used otherwise.
_session_secret = os.environ.get("SESSION_SECRET")
if not _session_secret:
    _session_secret = secrets.token_urlsafe(32)
    print("[dayboard] SESSION_SECRET not set - using an ephemeral dev secret. "
          "Set SESSION_SECRET in production so logins persist across restarts.")
app.add_middleware(SessionMiddleware, secret_key=_session_secret, same_site="lax")

# Static assets (PWA icons, manifest, service worker, offline page).
_STATIC_DIR = BASE_DIR / "web" / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(_STATIC_DIR / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Served from the root so its scope covers the whole app.
    return FileResponse(_STATIC_DIR / "sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache"})


def _redirect_uri(request: Request) -> str:
    """Where Google sends the user back. Overridable with OAUTH_REDIRECT_URI so
    it can be pinned to the exact https URL registered in the Google console
    (useful behind Render's proxy); otherwise derived from this request."""
    override = os.environ.get("OAUTH_REDIRECT_URI")
    if override:
        return override
    return str(request.url_for("oauth2callback"))


def get_provider(request: Request):
    """Return the active data provider for this request.

    GoogleProvider when the session carries valid credentials; SeedProvider
    otherwise. Any problem rebuilding credentials (expired, revoked, libraries
    missing) degrades cleanly to demo mode and notes the reason for the UI."""
    creds_data = request.session.get("credentials")
    if not creds_data:
        return SeedProvider()
    try:
        creds = google_auth.credentials_from_session(creds_data)
        # Persist a refreshed access token back to the session.
        request.session["credentials"] = google_auth.creds_to_session(creds)
        from .data.google import GoogleProvider
        return GoogleProvider(creds)
    except Exception as exc:  # noqa: BLE001 - degrade, don't 500
        request.session.pop("credentials", None)
        request.session["connect_error"] = (
            f"Google connection dropped ({exc.__class__.__name__}); "
            "showing the demo. Reconnect to go live again."
        )
        return SeedProvider()


# Today's brief is built once per session per day and reused on later opens, so
# the page settles for the day instead of regenerating (and, in live mode,
# re-reading Gmail and re-running the AI) on every refresh. /refresh forces a
# rebuild. In-memory and per-process: fine for a single-instance deploy, and it
# simply rebuilds after a restart. Keyed per session so one visitor's brief is
# never shown to another.
_BRIEF_CACHE: dict = {}


def _daypart(now=None):
    """Return (daypart, greeting, subline) from the local hour. The palette and
    the greeting both follow the time of day - this is a morning tool, so it
    should feel like the time you open it. The client refines this live."""
    from datetime import datetime as _dt
    h = (now or _dt.now()).hour
    if 5 <= h < 11:
        return "dawn", "Good morning", "Here's your day."
    if 11 <= h < 17:
        return "day", "Good afternoon", "Here's where things stand."
    if 17 <= h < 22:
        return "dusk", "Good evening", "Here's what you missed today."
    return "night", "Good evening", "Here's what you missed today."


def _greeting_name() -> str:
    return os.environ.get("DAYBOARD_USER_NAME", "").strip()


def _session_id(request: Request) -> str:
    sid = request.session.get("sid")
    if not sid:
        sid = secrets.token_urlsafe(16)
        request.session["sid"] = sid
    return sid


def _get_brief(request: Request):
    """Return (provider, brief) for this request, using today's cached brief if
    one exists for this session, otherwise building and caching it."""
    provider = get_provider(request)
    today = date.today().isoformat()
    key = (_session_id(request), today, provider.mode)
    brief = _BRIEF_CACHE.get(key)
    if brief is None:
        brief = build_brief(provider)
        _BRIEF_CACHE[key] = brief
        # Drop stale days so the cache does not grow without bound.
        for k in [k for k in _BRIEF_CACHE if k[1] != today]:
            _BRIEF_CACHE.pop(k, None)
    return provider, brief


def _clear_today(request: Request) -> None:
    today = date.today().isoformat()
    sid = request.session.get("sid")
    if not sid:
        return
    for mode in ("demo", "live"):
        _BRIEF_CACHE.pop((sid, today, mode), None)


def _render(request: Request):
    provider, brief = _get_brief(request)
    connect_error = request.session.pop("connect_error", None)
    flash = request.session.pop("flash", None)
    daypart, greeting, greeting_sub = _daypart()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "brief": brief,
            "data_mode": provider.mode,                 # "demo" or "live"
            "connected": provider.mode == "live",
            "llm_active": llm.is_configured(),
            "oauth_configured": google_auth.is_configured(),
            "connect_error": connect_error,
            "flash": flash,                             # {"kind": "ok"|"err", "text": ...}
            "daypart": daypart,                         # dawn|day|dusk|night
            "greeting": greeting,
            "greeting_sub": greeting_sub,
            "user_name": _greeting_name(),
        },
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return _render(request)


@app.get("/refresh")
def refresh(request: Request):
    """Force today's brief to rebuild from live data on the next load."""
    _clear_today(request)
    return RedirectResponse(url="/", status_code=303)


@app.get("/connect")
def connect(request: Request):
    """Kick off the Google OAuth flow."""
    try:
        url, state, code_verifier = google_auth.authorization_url(_redirect_uri(request))
    except google_auth.OAuthNotConfigured as exc:
        request.session["connect_error"] = str(exc)
        return RedirectResponse(url="/", status_code=303)
    except Exception as exc:  # libraries missing, bad config, etc.
        request.session["connect_error"] = (
            f"Could not start Google sign-in ({exc.__class__.__name__}). "
            "Check the Phase 2 setup in the README."
        )
        return RedirectResponse(url="/", status_code=303)
    request.session["oauth_state"] = state
    request.session["oauth_code_verifier"] = code_verifier
    return RedirectResponse(url=url, status_code=303)


@app.get("/oauth2callback", name="oauth2callback")
def oauth2callback(request: Request):
    """Google redirects here with ?code=...; swap it for tokens."""
    error = request.query_params.get("error")
    if error:
        request.session["connect_error"] = f"Google sign-in was cancelled ({error})."
        return RedirectResponse(url="/", status_code=303)

    state = request.session.pop("oauth_state", None)
    code_verifier = request.session.pop("oauth_code_verifier", None)
    if not state or state != request.query_params.get("state"):
        request.session["connect_error"] = "Sign-in state mismatch; please try again."
        return RedirectResponse(url="/", status_code=303)

    try:
        creds_data = google_auth.exchange_code(
            _redirect_uri(request), state, str(request.url),
            code_verifier=code_verifier,
        )
    except Exception as exc:  # noqa: BLE001
        # Log Google's actual reason (oauthlib puts it on .description) so a
        # failure is diagnosable from the server console, not just a class name.
        detail = getattr(exc, "description", "") or str(exc)
        print(f"[dayboard] token exchange failed: {exc.__class__.__name__}: {detail}")
        request.session["connect_error"] = (
            f"Could not finish Google sign-in ({exc.__class__.__name__})"
            + (f": {detail}" if detail else "") + "."
        )
        return RedirectResponse(url="/", status_code=303)

    request.session["credentials"] = creds_data
    return RedirectResponse(url="/", status_code=303)


@app.get("/disconnect")
def disconnect(request: Request):
    """Forget the Google account and drop back to the demo."""
    request.session.pop("credentials", None)
    request.session.pop("oauth_state", None)
    return RedirectResponse(url="/", status_code=303)


@app.post("/send")
def send_reply(request: Request, email_id: str = Form(...), reply: str = Form(...)):
    """Send an approved reply. Only works in live mode (a real Gmail account);
    the demo inbox has no real recipients to send to. The reply text is whatever
    the user approved or edited in the UI - nothing is sent that they did not
    submit."""
    provider = get_provider(request)
    if provider.mode != "live":
        request.session["flash"] = {
            "kind": "err",
            "text": "Connect your Google account to send replies.",
        }
        return RedirectResponse(url="/", status_code=303)

    try:
        result = provider.send_reply(email_id, reply)
    except ValueError as exc:
        request.session["flash"] = {"kind": "err", "text": f"Could not send: {exc}."}
        return RedirectResponse(url="/", status_code=303)
    except Exception as exc:  # noqa: BLE001 - surface, don't 500
        request.session["flash"] = {
            "kind": "err",
            "text": f"Sending failed ({exc.__class__.__name__}). Please try again.",
        }
        return RedirectResponse(url="/", status_code=303)

    request.session["flash"] = {"kind": "ok", "text": f"Reply sent to {result['to']}."}
    return RedirectResponse(url="/", status_code=303)


@app.get("/api/brief")
def api_brief(request: Request):
    """JSON version of the brief - what the scheduled job and the email sender
    would consume."""
    _, brief = _get_brief(request)
    return JSONResponse({
        "generated_at": brief.generated_at.isoformat(),
        "mode": brief.mode,
        "summary": brief.summary,
        "items": [i.to_dict() for i in brief.items],
        "conflicts": [
            {"event_a": c.event_a, "event_b": c.event_b,
             "overlap_start": c.overlap_start.isoformat(),
             "overlap_end": c.overlap_end.isoformat()}
            for c in brief.conflicts
        ],
        "action_items": brief.action_items,
    })


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
