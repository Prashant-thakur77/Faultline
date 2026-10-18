"""Where a page lands (M19).

* **in-app**: always. The (:Page) node in FalkorDB IS the in-app pager; nothing is sent anywhere for it.
* **webhook**: a Slack-compatible incoming webhook (`FAULTLINE_WEBHOOK_URL`): a Block Kit message with the deep link.
* **telegram**: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`: one message with an *Ack* button (callback `ack:<page id>`,
  answered by POST /api/telegram/webhook, authenticated by `TELEGRAM_WEBHOOK_SECRET` and `TELEGRAM_ALLOWED_IDS`).
* **pagerduty**: `PAGERDUTY_ROUTING_KEY`: Events API v2, trigger on a page or escalation, resolve when the incident
  resolves, deduplicated per incident.
* **email**: AWS SES (`FAULTLINE_SES_FROM`, `FAULTLINE_SES_TO`, region from `FAULTLINE_SES_REGION` or the AWS
  environment). boto3 is an OPTIONAL import: without it the channel reports "boto3 not installed".

The on-call path (actions/oncall.deliver_wave) calls `send` ONCE per wave (the pages one write made for one incident):
the webhook, PagerDuty and the inbox get one message listing everyone paged, each with their own signed ack link.

Standard library only (urllib), short timeouts, never raises: a slow or failing channel must never break a run, the
escalation tick or an ack. What each channel did is returned to the caller, which records it on the Page
(writes.record_delivery). Secrets are read from settings and never logged or returned.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from ..config import settings

log = logging.getLogger("faultline.channels")

TIMEOUT_S = 5
PD_URL = "https://events.pagerduty.com/v2/enqueue"

# event kind → (PagerDuty action, severity); None = not sent to PagerDuty (informational)
PD = {"page": ("trigger", "critical"), "escalation": ("trigger", "critical"), "resolved": ("resolve", "info"),
      "contract_notice": (None, "info"), "report": (None, "info")}
ICON = {"page": "[PAGE]", "escalation": "[ESCALATED]", "resolved": "[RESOLVED]", "contract_notice": "[HANDLED UNDER CONTRACT]",
        "report": "[HAND-OFF]"}


def configured() -> list[dict[str, Any]]:
    """Every channel and whether it is configured (no secret values: only which settings are present)."""
    ses = bool(settings.faultline_ses_from and settings.faultline_ses_to)
    boto = _boto3_available() if ses else None
    return [
        {"channel": "in_app", "configured": True, "detail": "the in-app pager (the Page node in FalkorDB); always on"},
        {"channel": "webhook", "configured": bool(settings.faultline_webhook_url),
         "detail": "Slack-compatible incoming webhook" if settings.faultline_webhook_url else "set FAULTLINE_WEBHOOK_URL"},
        {"channel": "telegram", "configured": bool(settings.telegram_bot_token and (settings.telegram_chat_id
                                                                                     or settings.telegram_people)),
         "detail": ("the on-call bot: one card per chat per incident wave, listing everyone paged (edited in place), "
                    "to the paged person's linked chat or the shared chat" + ("" if settings.telegram_webhook_secret and settings.telegram_people
                                     else "; buttons and commands inactive until TELEGRAM_WEBHOOK_SECRET and "
                                          "TELEGRAM_PEOPLE are set"))
         if settings.telegram_bot_token and (settings.telegram_chat_id or settings.telegram_people)
         else "set TELEGRAM_BOT_TOKEN, and TELEGRAM_CHAT_ID or TELEGRAM_PEOPLE"},
        {"channel": "pagerduty", "configured": bool(settings.pagerduty_routing_key),
         "detail": "Events API v2, deduplicated per incident" if settings.pagerduty_routing_key else "set PAGERDUTY_ROUTING_KEY"},
        {"channel": "email", "configured": ses and bool(boto),
         "detail": ("AWS SES" if boto else "AWS SES configured but boto3 is not installed (pip install boto3)") if ses
         else "set FAULTLINE_SES_FROM and FAULTLINE_SES_TO (AWS SES, needs boto3)"},
    ]


def external() -> list[str]:
    return [c["channel"] for c in configured() if c["configured"] and c["channel"] != "in_app"]


def _boto3_available() -> bool:
    try:
        import boto3  # noqa: F401
    except ImportError:
        return False
    return True


def _post(url: str, payload: dict, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - fixed https endpoints / operator URL
            ok = 200 <= int(resp.status) < 300
            return {"ok": ok, "status": int(resp.status)}
    except Exception as e:  # noqa: BLE001 - a chat or paging outage must never break the caller
        host = url.split("/")[2] if "//" in url else "?"
        log.warning("channel post to %s failed: %s", host, type(e).__name__)
        return {"ok": False, "error": type(e).__name__}


# ------------------------------------------------------------------ payloads (pure; unit-tested)
def slack_payload(kind: str, title: str, text: str, *, incident: str | None, link: str) -> dict:
    blocks: list[dict] = [{"type": "header", "text": {"type": "plain_text", "text": f"{ICON.get(kind, '')} {title}"[:150]}},
                          {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}]
    if link:
        btn: dict = {"type": "button", "text": {"type": "plain_text", "text": "Open in Faultline"}, "url": link}
        if kind in ("page", "escalation"):
            btn["style"] = "primary"   # Slack rejects a null style, so it is only set when there is one
        blocks.append({"type": "actions", "elements": [btn]})
    if incident:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"incident `{incident}`"}]})
    return {"text": f"{title}: {text[:200]}", "blocks": blocks}


def pagerduty_payload(kind: str, title: str, text: str, *, tenant: str, incident: str | None, link: str,
                      routing_key: str) -> dict | None:
    action, severity = PD.get(kind, (None, "info"))
    if action is None:
        return None
    out: dict = {"routing_key": routing_key, "event_action": action, "dedup_key": f"faultline:{tenant}:{incident or title}"}
    if action == "trigger":
        out["payload"] = {"summary": title[:1024], "source": "faultline", "severity": severity,
                          "custom_details": {"detail": text[:4000], "incident": incident, "tenant": tenant}}
        if link:
            out["links"] = [{"href": link, "text": "Open in Faultline"}]
    return out


def telegram_payload(kind: str, title: str, text: str, *, page_id: str | None, link: str, chat_id: str) -> dict:
    out: dict = {"chat_id": chat_id, "text": f"{ICON.get(kind, '')} {title}\n{text}"[:4000], "disable_web_page_preview": True}
    row: list[dict] = []
    if link and link.startswith("http"):  # Telegram refuses relative URLs on buttons
        row.append({"text": "Open", "url": link})
    if page_id and kind in ("page", "escalation"):
        row.append({"text": "Ack", "callback_data": f"ack:{page_id}"[:64]})
    if row:
        out["reply_markup"] = {"inline_keyboard": [row]}
    return out


# ------------------------------------------------------------------ senders
def _telegram(method: str, payload: dict) -> dict:
    """Through the bot module's client (the token is used in one place only, and never logged)."""
    from . import telegram

    res = telegram.call(method, payload)
    return {"ok": bool(res.get("ok")), **({} if res.get("ok") else {"error": res.get("description")})}


def _email(subject: str, body: str) -> dict:
    try:
        import boto3  # optional dependency: the channel is off without it
    except ImportError:
        return {"ok": False, "error": "boto3 not installed"}
    try:
        from botocore.config import Config   # ships with boto3

        kw = {"region_name": settings.faultline_ses_region} if settings.faultline_ses_region else {}
        # short timeouts and one attempt: a slow SES must never hold a delivery worker (security review M19 #8)
        ses = boto3.client("ses", config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1}), **kw)
        to = [x.strip() for x in settings.faultline_ses_to.split(",") if x.strip()]
        ses.send_email(Source=settings.faultline_ses_from, Destination={"ToAddresses": to},
                       Message={"Subject": {"Data": subject[:200]}, "Body": {"Text": {"Data": body[:8000]}}})
        return {"ok": True}
    except Exception as e:  # noqa: BLE001 - credentials, region, sandbox recipients...: recorded, never raised
        log.warning("SES send failed: %s", type(e).__name__)
        return {"ok": False, "error": type(e).__name__}


def send(kind: str, title: str, text: str, *, tenant: str, incident: str | None, page_id: str | None, link: str,
         skip: tuple[str, ...] = ()) -> dict:
    """Fan one event out to every configured external channel (except `skip`: the on-call path sends Telegram its
    rich card instead). Returns {channel: {ok, …}} for those attempted (in-app is the Page itself, always delivered)."""
    out: dict[str, dict] = {"in_app": {"ok": True}}
    if "webhook" not in skip and settings.faultline_webhook_url:
        out["webhook"] = _post(settings.faultline_webhook_url, slack_payload(kind, title, text, incident=incident, link=link))
    if "telegram" not in skip and settings.telegram_bot_token and settings.telegram_chat_id:
        out["telegram"] = _telegram("sendMessage", telegram_payload(kind, title, text, page_id=page_id, link=link,
                                                                    chat_id=settings.telegram_chat_id))
    if "pagerduty" not in skip and settings.pagerduty_routing_key:
        pd = pagerduty_payload(kind, title, text, tenant=tenant, incident=incident, link=link,
                               routing_key=settings.pagerduty_routing_key)
        if pd is not None:
            out["pagerduty"] = _post(PD_URL, pd)
    if "email" not in skip and settings.faultline_ses_from and settings.faultline_ses_to:
        out["email"] = _email(f"Faultline {ICON.get(kind, '')} {title}", f"{text}\n\n{link}".strip())
    return out


def telegram_answer(callback_id: str, text: str) -> None:
    """Close the spinner on the Ack button (best effort)."""
    _telegram("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:180]})


def telegram_secret_ok(given: str) -> bool:
    import hmac

    want = settings.telegram_webhook_secret
    return bool(want) and hmac.compare_digest(given.encode(), want.encode())


def telegram_allowed(user_id: Any) -> bool:
    """A Telegram user the operator mapped to a person (TELEGRAM_PEOPLE): the only users the bot acts for."""
    from . import telegram_bot

    return str(user_id) in telegram_bot.people_map()


__all__ = ["configured", "external", "send", "slack_payload", "pagerduty_payload", "telegram_payload", "telegram_answer",
           "telegram_secret_ok", "telegram_allowed"]
