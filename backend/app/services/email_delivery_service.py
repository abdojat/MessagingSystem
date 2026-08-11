import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit

from app.core.config import Settings


class EmailDeliveryError(Exception):
    """Controlled provider boundary; provider details never reach API clients."""


class VerificationMailer(Protocol):
    async def send_verification(self, recipient: str, verification_url: str) -> None: ...


@dataclass(frozen=True)
class CapturedVerificationEmail:
    recipient: str
    verification_url: str


class CaptureVerificationMailer:
    """Deterministic in-memory transport for tests and explicit local capture."""

    def __init__(self) -> None:
        self.messages: list[CapturedVerificationEmail] = []

    async def send_verification(self, recipient: str, verification_url: str) -> None:
        self.messages.append(CapturedVerificationEmail(recipient=recipient, verification_url=verification_url))


class ConsoleVerificationMailer:
    """Development-only convenience transport; production configuration rejects it."""

    async def send_verification(self, recipient: str, verification_url: str) -> None:
        print(
            f"DEVELOPMENT EMAIL VERIFICATION for {recipient}: {verification_url}",
            flush=True,
        )


class SmtpVerificationMailer:
    def __init__(self, settings: Settings) -> None:
        self._host = settings.smtp_host.strip()
        self._port = settings.smtp_port
        self._username = settings.smtp_username.strip()
        self._password = settings.smtp_password.get_secret_value()
        self._from_email = str(settings.smtp_from_email or "")
        self._use_tls = settings.smtp_use_tls
        self._use_starttls = settings.smtp_use_starttls

    async def send_verification(self, recipient: str, verification_url: str) -> None:
        try:
            await asyncio.to_thread(self._send_sync, recipient, verification_url)
        except Exception as exc:
            raise EmailDeliveryError("verification email delivery failed") from exc

    def _send_sync(self, recipient: str, verification_url: str) -> None:
        message = EmailMessage()
        message["Subject"] = "Verify your MessagingSystem email"
        message["From"] = self._from_email
        message["To"] = recipient
        message.set_content(
            "Verify the email address on your MessagingSystem account by opening this link:\n\n"
            f"{verification_url}\n\n"
            "If you did not request this message, you can ignore it."
        )

        context = ssl.create_default_context()
        if self._use_tls:
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                self._host,
                self._port,
                timeout=15,
                context=context,
            )
        else:
            client = smtplib.SMTP(self._host, self._port, timeout=15)

        with client:
            client.ehlo()
            if self._use_starttls:
                client.starttls(context=context)
                client.ehlo()
            if self._username:
                client.login(self._username, self._password)
            client.send_message(message)


def build_verification_url(public_url: str, token: str) -> str:
    parsed = urlsplit(public_url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", urlencode({"token": token})))


def build_verification_mailer(settings: Settings) -> VerificationMailer:
    if settings.email_delivery_mode == "smtp":
        return SmtpVerificationMailer(settings)
    if settings.email_delivery_mode == "capture":
        return CaptureVerificationMailer()
    return ConsoleVerificationMailer()
