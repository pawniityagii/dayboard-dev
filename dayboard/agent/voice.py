"""Optional writing-voice profile for reply drafts.

If you describe how you write (and optionally paste a couple of example lines),
the LLM drafting step mirrors it so suggested replies sound like you instead of
generic. Entirely optional: with nothing set, drafting is unchanged.

Resolution order:
  1. DAYBOARD_VOICE_FILE - path to a text/markdown file.
  2. voice.md at the project root (copy voice.example.md to start).
  3. DAYBOARD_VOICE - the profile text inline in an env var.

Never raises: a missing file or unreadable path just means no voice guidance,
not a broken draft.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# project root: dayboard/agent/voice.py -> parents[2]
_DEFAULT_FILE = Path(__file__).resolve().parents[2] / "voice.md"
_MAX_CHARS = 4000  # keep the prompt bounded even if the file is large


def guidance() -> Optional[str]:
    """Return the voice-profile text, or None if none is configured."""
    text: Optional[str] = None
    try:
        env_path = os.environ.get("DAYBOARD_VOICE_FILE")
        if env_path and Path(env_path).is_file():
            text = Path(env_path).read_text(encoding="utf-8")
        elif _DEFAULT_FILE.is_file():
            text = _DEFAULT_FILE.read_text(encoding="utf-8")
    except Exception:
        text = None
    if not text:
        text = os.environ.get("DAYBOARD_VOICE")
    if not text or not text.strip():
        return None
    return text.strip()[:_MAX_CHARS]
