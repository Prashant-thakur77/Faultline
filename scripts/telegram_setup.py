"""Set up the Faultline on-call bot's profile on Telegram, idempotently, from the server's environment.

    PYTHONPATH=backend uv run python scripts/telegram_setup.py [--photo frontend/src/app/apple-icon.png] [--check]

Reads TELEGRAM_BOT_TOKEN, FAULTLINE_PUBLIC_URL and TELEGRAM_WEBHOOK_SECRET from the environment / .env (never prints
them). Calls setMyCommands, setMyDescription, setMyShortDescription, setWebhook (FAULTLINE_PUBLIC_URL +
/api/telegram/webhook, the secret token, message and callback_query updates only) and getWebhookInfo to verify; with
--photo, setMyProfilePhoto when the Bot API offers it (it reports when it does not). Every call is safe to repeat.
--check only reads (getMe, getWebhookInfo).
"""

from __future__ import annotations

import argparse
import mimetypes
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from faultline.actions import telegram as tg  # noqa: E402
from faultline.config import settings  # noqa: E402

ALLOWED_UPDATES = ["message", "callback_query"]


def say(step: str, res: dict) -> bool:
    ok = bool(res.get("ok"))
    print(f"  {'OK  ' if ok else 'FAIL'} {step}" + ("" if ok else f": {tg.scrub(str(res.get('description')))}"))
    return ok


def photo(path: Path) -> dict:
    """setMyProfilePhoto takes multipart (InputProfilePhotoStatic). Built here so the token stays in tg._http's URL."""
    import json
    import urllib.request

    data = path.read_bytes()
    boundary = f"----faultline{uuid.uuid4().hex}"
    ctype = mimetypes.guess_type(path.name)[0] or "image/png"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"\r\n\r\n"
            f"{json.dumps({'type': 'static', 'photo': 'attach://logo'})}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"logo\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(tg.API.format(token=settings.telegram_bot_token, method="setMyProfilePhoto"), data=body,
                                 headers={"content-type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=tg.TIMEOUT_S) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001 - older Bot API versions do not have the method; never print the URL
        return {"ok": False, "description": type(e).__name__}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", default="")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if not tg.configured():
        print("TELEGRAM_BOT_TOKEN is not set (server .env): nothing to do")
        return 2
    me = tg.call("getMe", {})
    if not say("getMe", me):
        return 1
    print(f"  bot @{me['result'].get('username')}")
    if a.check:
        info = tg.call("getWebhookInfo", {})
        say("getWebhookInfo", info)
        r = info.get("result") or {}
        print(f"  webhook {'set' if r.get('url') else 'NOT set'}; pending {r.get('pending_update_count')}; "
              f"last error {r.get('last_error_message') or 'none'}")
        return 0
    ok = say("setMyCommands", tg.call("setMyCommands", {"commands": [{"command": c, "description": d}
                                                                     for c, d in tg.COMMANDS]}))
    ok &= say("setMyDescription", tg.call("setMyDescription", {"description": tg.DESCRIPTION}))
    ok &= say("setMyShortDescription", tg.call("setMyShortDescription", {"short_description": tg.SHORT_DESCRIPTION}))
    base = settings.faultline_public_url.rstrip("/")
    if not base.startswith("https://"):
        print("  SKIP setWebhook: FAULTLINE_PUBLIC_URL must be an https URL Telegram can reach")
        ok = False
    elif not settings.telegram_webhook_secret:
        print("  SKIP setWebhook: TELEGRAM_WEBHOOK_SECRET is not set (the API refuses unauthenticated updates)")
        ok = False
    else:
        ok &= say("setWebhook", tg.call("setWebhook", {"url": f"{base}/api/telegram/webhook",
                                                       "secret_token": settings.telegram_webhook_secret,
                                                       "allowed_updates": ALLOWED_UPDATES, "drop_pending_updates": False}))
        info = tg.call("getWebhookInfo", {})
        r = info.get("result") or {}
        ok &= say("getWebhookInfo (url matches)", {"ok": r.get("url") == f"{base}/api/telegram/webhook",
                                                   "description": "the webhook URL Telegram holds differs"})
        print(f"  pending updates {r.get('pending_update_count')}; last error {r.get('last_error_message') or 'none'}")
    if a.photo:
        path = Path(a.photo)
        if path.exists():
            say("setMyProfilePhoto", photo(path))
        else:
            print(f"  SKIP setMyProfilePhoto: {path} not found")
    if not settings.telegram_people:
        print("  NOTE TELEGRAM_PEOPLE is empty: the bot will answer /start with each user's id and act for nobody")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
