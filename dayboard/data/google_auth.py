"""OAuth 2.0 plumbing for the real Google mode.

Kept separate from google.py so the provider stays about *data* and this stays
about *auth*. Everything here is lazy about the Google libraries: nothing is
imported from google.* at module load, so demo mode runs even when the Phase 2
dependencies are not installed. The libraries are only touched once a user
actually starts the connect flow.

Credentials are never written to disk. The OAuth token lives in the signed
session cookie (see app.py); this module just converts between a Google
Credentials object and the plain dict we put in the session.
"""
from __future__ import annotations

import os
from typing import Optional

# Read access to triage the inbox and calendar, plus gmail.send so an approved
# reply can actually go out. gmail.send only permits sending - it grants no
# extra read access - and a reply is sent only when the user clicks
# "Approve & send", so "nothing is sent without your approval" still holds.
# NOTE: adding a scope invalidates older tokens; users must reconnect once.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


class OAuthNotConfigured(Exception):
    """Raised when the Google client credentials are not set up in the
    environment. The caller turns this into a clear message in the UI instead
    of a 500."""


def is_configured() -> bool:
    """True if the server has enough to start an OAuth flow."""
    if os.environ.get("GOOGLE_CLIENT_SECRETS_FILE"):
        return True
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and
                os.environ.get("GOOGLE_CLIENT_SECRET"))


def _client_config() -> dict:
    """Build the client_config dict google-auth expects.

    Two ways to supply credentials:
      - GOOGLE_CLIENT_SECRETS_FILE: path to the client_secret.json Google gives
        you. Used verbatim if present.
      - GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET: the two values on their own,
        assembled into the same structure. Handy on Render where you set env
        vars rather than ship a file.
    """
    secrets_file = os.environ.get("GOOGLE_CLIENT_SECRETS_FILE")
    if secrets_file:
        import json
        with open(secrets_file, "r", encoding="utf-8") as fh:
            return json.load(fh)

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not (client_id and client_secret):
        raise OAuthNotConfigured(
            "Set GOOGLE_CLIENT_SECRETS_FILE, or GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET, to connect a Google account."
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }


def _flow(redirect_uri: str, state: Optional[str] = None):
    """A configured google-auth-oauthlib Flow. Google libs imported lazily.

    Config is resolved first so a missing GOOGLE_CLIENT_ID/SECRET surfaces the
    actionable OAuthNotConfigured message even if the Phase 2 libraries are not
    yet installed."""
    config = _client_config()
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(config, scopes=SCOPES, state=state)
    flow.redirect_uri = redirect_uri
    return flow


def authorization_url(redirect_uri: str) -> tuple[str, str, Optional[str]]:
    """Return (url, state, code_verifier). Send the user to url; keep state and
    code_verifier in the session for the callback. access_type=offline +
    prompt=consent so we get a refresh token. The library uses PKCE by default,
    generating a one-time code_verifier that MUST be replayed at token exchange,
    so it is returned here to be stashed and passed back to exchange_code."""
    flow = _flow(redirect_uri)
    url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return url, state, getattr(flow, "code_verifier", None)


def exchange_code(redirect_uri: str, state: str, authorization_response: str,
                  code_verifier: Optional[str] = None) -> dict:
    """Finish the dance: swap the ?code=... callback for tokens. The PKCE
    code_verifier from the authorization step must be replayed here, or Google
    rejects the exchange with invalid_grant. Returns the session-safe dict to
    stash in the cookie."""
    flow = _flow(redirect_uri, state=state)
    if code_verifier is not None:
        flow.code_verifier = code_verifier
    flow.fetch_token(authorization_response=authorization_response)
    return creds_to_session(flow.credentials)


def creds_to_session(creds) -> dict:
    """Flatten a Credentials object into the plain dict we keep in the session."""
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }


def credentials_from_session(data: dict):
    """Rebuild a Credentials object from the session dict. Refreshes it in place
    if the access token has expired and we hold a refresh token; the caller is
    responsible for writing the refreshed dict back to the session."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request as GoogleAuthRequest

    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
    return creds
