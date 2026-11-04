import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from html import escape
from pathlib import Path

from app.config import ROOT, env

log = logging.getLogger(__name__)


def app_url() -> str:
    return env("ORION_APP_URL", "http://localhost:5173").rstrip("/")


def _outbox_dir() -> Path:
    path = ROOT / "data" / "mail"
    path.mkdir(parents=True, exist_ok=True)
    return path


def send_mail(
    to_address: str,
    subject: str,
    text: str,
    html: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
    reply_to: str | None = None,
    raise_on_error: bool = False,
) -> None:
    from_address = env("ORION_SMTP_FROM", "orion@localhost").strip()
    from_name = env("ORION_SMTP_FROM_NAME", "Prakash Securities").strip()
    message = EmailMessage()
    message["From"] = formataddr((from_name, from_address)) if from_name else from_address
    message["To"] = to_address
    message["Reply-To"] = (reply_to or from_address).strip()
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    domain = from_address.rsplit("@", 1)[-1] if "@" in from_address else "localhost"
    message["Message-ID"] = make_msgid(domain=domain)
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    for filename, data, content_type in attachments or []:
        maintype, _, subtype = (content_type or "application/octet-stream").partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        message.add_attachment(
            data,
            maintype=maintype or "application",
            subtype=subtype,
            filename=filename,
        )

    host = env("ORION_SMTP_HOST").strip()
    if not host:
        log.warning("ORION_SMTP_HOST is empty; writing mail to outbox")
        _write_outbox(to_address, from_address, subject, text)
        if raise_on_error:
            raise RuntimeError("Email is not configured.")
        return

    port = int(env("ORION_SMTP_PORT", "587"))
    user = env("ORION_SMTP_USER").strip()
    password = env("ORION_SMTP_PASSWORD").replace(" ", "").strip()
    use_tls = env("ORION_SMTP_TLS", "1") != "0"
    context = ssl.create_default_context()

    try:
        _smtp_send(host, port, user, password, use_tls, context, message)
        log.info("Sent mail to %s via %s:%s", to_address, host, port)
        return
    except Exception as first_error:
        log.warning("SMTP %s:%s failed: %s: %s", host, port, type(first_error).__name__, first_error)
        smtp_error: BaseException = first_error
        if use_tls:
            try:
                with smtplib.SMTP_SSL(host, 465, timeout=40, context=context) as smtp:
                    if user:
                        smtp.login(user, password)
                    smtp.send_message(message)
                log.info("Sent mail to %s via %s:465", to_address, host)
                return
            except Exception as ssl_error:
                log.exception("SMTP SSL %s:465 also failed; writing mail to outbox", host)
                smtp_error = ssl_error
        else:
            log.exception("SMTP send failed; writing mail to outbox")
        _write_outbox(to_address, from_address, subject, text, error=repr(smtp_error))
        if raise_on_error:
            raise RuntimeError("Could not send the email. Try again in a moment.") from smtp_error


def _smtp_send(
    host: str,
    port: int,
    user: str,
    password: str,
    use_tls: bool,
    context: ssl.SSLContext,
    message: EmailMessage,
) -> None:
    if use_tls:
        with smtplib.SMTP(host, port, timeout=40) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            if user:
                smtp.login(user, password)
            smtp.send_message(message)
        return
    with smtplib.SMTP(host, port, timeout=40) as smtp:
        if user:
            smtp.login(user, password)
        smtp.send_message(message)


def _write_outbox(
    to_address: str,
    from_address: str,
    subject: str,
    text: str,
    error: str | None = None,
) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in to_address)
    target = _outbox_dir() / f"{stamp}-{safe}.txt"
    extra = f"\nSMTP error: {error}\n" if error else ""
    target.write_text(
        f"To: {to_address}\nFrom: {from_address}\nSubject: {subject}\n{extra}\n{text}\n",
        encoding="utf-8",
    )
    log.info("Wrote mail to %s", target)


def send_password_reset(
    to_address: str,
    display_name: str,
    token: str,
    *,
    by_admin: bool = False,
    raise_on_error: bool = False,
) -> None:
    link = f"{app_url()}/reset-password?token={token}"
    name = display_name or "there"
    if by_admin:
        reason = "An administrator sent a password reset for your Prakash Securities account. "
    else:
        reason = "A password reset was requested for your Prakash Securities account. "
    text = (
        f"Hi {name},\n\n"
        f"{reason}"
        "The link below expires in one hour:\n\n"
        f"{link}\n\n"
        "If you did not expect this, ignore this message. Your password will not change.\n\n"
        "Prakash Securities\n"
    )
    safe_name = escape(name)
    safe_link = escape(link, quote=True)
    html = (
        f"<p>Hi {safe_name},</p>"
        f"<p>{escape(reason)}This link expires in one hour.</p>"
        f'<p><a href="{safe_link}">Set a new password</a></p>'
        f"<p>Or paste this address into your browser:<br>{safe_link}</p>"
        "<p>If you did not expect this, ignore this message. Your password will not change.</p>"
        "<p>Prakash Securities</p>"
    )
    send_mail(
        to_address,
        "Prakash Securities account password reset",
        text,
        html,
        raise_on_error=raise_on_error,
    )


def send_account_ready(to_address: str, display_name: str, username: str) -> None:
    link = f"{app_url()}/login"
    name = display_name or "there"
    text = (
        f"Hi {name},\n\n"
        "Your Prakash Securities account is ready to use. Sign in with the username "
        f"you chose ({username}) and the password you set when you requested access.\n\n"
        f"{link}\n\n"
        "If you did not request this account, ignore this message.\n\n"
        "Prakash Securities\n"
    )
    safe_name = escape(name)
    safe_user = escape(username)
    safe_link = escape(link, quote=True)
    html = (
        f"<p>Hi {safe_name},</p>"
        "<p>Your Prakash Securities account is ready to use. Sign in with the username "
        f"you chose (<strong>{safe_user}</strong>) and the password you set when you requested access.</p>"
        f'<p><a href="{safe_link}">Sign in</a></p>'
        f"<p>Or paste this address into your browser:<br>{safe_link}</p>"
        "<p>If you did not request this account, ignore this message.</p>"
        "<p>Prakash Securities</p>"
    )
    send_mail(to_address, "Your Prakash Securities account is ready", text, html)


def helpdesk_address() -> str:
    return env("ORION_SUPPORT_EMAIL") or env("ORION_SMTP_FROM", "orion@localhost").strip()


def send_support_request(
    user: dict,
    subject: str,
    details: str,
    attachments: list[tuple[str, bytes, str]],
) -> None:
    helpdesk = helpdesk_address()
    display = user.get("display_name") or user.get("username") or "User"
    username = user.get("username") or ""
    role = user.get("role") or ""
    email = (user.get("email") or "").strip()
    phone = (user.get("phone") or "").strip()
    names = [name for name, _data, _ctype in attachments] or ["none"]
    text = (
        f"A user raised a request in Prakash Securities.\n\n"
        f"From: {display} ({username})\n"
        f"Role: {role}\n"
        f"Email: {email or 'not on file'}\n"
        f"Phone: {phone or 'not on file'}\n"
        f"Subject: {subject}\n\n"
        f"{details}\n\n"
        f"Attachments: {', '.join(names)}\n"
    )
    html = (
        "<p>A user raised a request in Prakash Securities.</p>"
        "<table>"
        f"<tr><td><strong>From</strong></td><td>{escape(display)} ({escape(username)})</td></tr>"
        f"<tr><td><strong>Role</strong></td><td>{escape(role)}</td></tr>"
        f"<tr><td><strong>Email</strong></td><td>{escape(email or 'not on file')}</td></tr>"
        f"<tr><td><strong>Phone</strong></td><td>{escape(phone or 'not on file')}</td></tr>"
        f"<tr><td><strong>Subject</strong></td><td>{escape(subject)}</td></tr>"
        "</table>"
        f"<p>{escape(details).replace(chr(10), '<br>')}</p>"
        f"<p><strong>Attachments:</strong> {escape(', '.join(names))}</p>"
    )
    send_mail(
        helpdesk,
        f"[Request] {subject} — {display}",
        text,
        html,
        attachments=attachments,
        reply_to=email or None,
        raise_on_error=True,
    )
