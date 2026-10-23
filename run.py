"""Run Dayboard locally.

    python run.py

Then open http://127.0.0.1:8000 in your browser.

Demo mode (no setup): runs on sample data out of the box.
Live mode: set GEMINI_API_KEY to turn on real AI reasoning. Real Gmail/Calendar
reading is added in Phase 2 (see README).
"""
import os

import uvicorn

if __name__ == "__main__":
    # Local dev only. This entrypoint serves over http://127.0.0.1, and Google's
    # OAuth library (oauthlib) refuses to finish a sign-in over plain http unless
    # told otherwise. Safe here because it is localhost-only; production serves
    # over https and does not use run.py, so it never relaxes this.
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
    uvicorn.run("dayboard.app:app", host="127.0.0.1", port=8000, reload=True)
