import hashlib
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage

from config import (
    EMAIL_FROM,
    EMAIL_VERIFICATION_EXPIRY_MINUTES,
    PASSWORD_RESET_EXPIRY_MINUTES,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
)


def email_delivery_configured():
    return bool(SMTP_HOST and EMAIL_FROM)


def create_verification_token():
    return secrets.token_urlsafe(32)


def hash_verification_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verification_expiry():
    return (
        datetime.now() + timedelta(minutes=EMAIL_VERIFICATION_EXPIRY_MINUTES)
    ).isoformat(timespec="seconds")


def password_reset_expiry():
    return (
        datetime.now() + timedelta(minutes=PASSWORD_RESET_EXPIRY_MINUTES)
    ).isoformat(timespec="seconds")


def send_verification_email(to_email, first_name, verification_url):
    if not email_delivery_configured():
        raise RuntimeError(
            "Email delivery is not configured on this server."
        )

    message = EmailMessage()
    message["Subject"] = "Verify your BAS Automation email"
    message["From"] = EMAIL_FROM
    message["To"] = to_email

    greeting = f"Hi {first_name}," if first_name else "Hello,"
    message.set_content(
        "\n".join(
            [
                greeting,
                "",
                "Verify your email address to activate your BAS Automation account:",
                verification_url,
                "",
                (
                    "This verification link expires in "
                    f"{EMAIL_VERIFICATION_EXPIRY_MINUTES} minutes."
                ),
                "",
                "If you did not create this account, you can ignore this email.",
            ]
        )
    )

    if SMTP_USE_SSL:
        smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20)
    else:
        smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)

    try:
        if not SMTP_USE_SSL and SMTP_USE_TLS:
            smtp.starttls()

        if SMTP_USERNAME:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD or "")

        smtp.send_message(message)
    finally:
        try:
            smtp.quit()
        except Exception:
            smtp.close()


def send_password_reset_email(to_email, first_name, reset_url):
    if not email_delivery_configured():
        raise RuntimeError(
            "Email delivery is not configured on this server."
        )

    message = EmailMessage()
    message["Subject"] = "Reset your BAS Automation password"
    message["From"] = EMAIL_FROM
    message["To"] = to_email

    greeting = f"Hi {first_name}," if first_name else "Hello,"
    message.set_content(
        "\n".join(
            [
                greeting,
                "",
                "We received a request to reset your BAS Automation password.",
                "Use this link to choose a new password:",
                reset_url,
                "",
                (
                    "This password reset link expires in "
                    f"{PASSWORD_RESET_EXPIRY_MINUTES} minutes."
                ),
                "",
                "If you did not request a password reset, you can ignore this email.",
            ]
        )
    )

    if SMTP_USE_SSL:
        smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20)
    else:
        smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20)

    try:
        if not SMTP_USE_SSL and SMTP_USE_TLS:
            smtp.starttls()

        if SMTP_USERNAME:
            smtp.login(SMTP_USERNAME, SMTP_PASSWORD or "")

        smtp.send_message(message)
    finally:
        try:
            smtp.quit()
        except Exception:
            smtp.close()
