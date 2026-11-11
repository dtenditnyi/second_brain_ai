"""Two-factor login with TOTP (Round 5, F7).

* The secret is created on "setup" and kept only in the session until the owner confirms it
  with a code; then it is stored encrypted (``EncryptedCharField``) in ``UserSettings``.
* 10 one-time backup codes are shown once; only their SHA-256 hashes are stored and a used
  code is removed. A TOTP step that was already accepted cannot be reused (replay).
* API tokens (``/api/v1/``) are not affected: they are a separate, scoped credential.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

import pyotp
import segno

ISSUER = "Second Brain"
BACKUP_COUNT = 10
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def new_secret():
    return pyotp.random_base32()


def otpauth_url(username, secret):
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=ISSUER)


def qr_svg(url):
    svg = segno.make(url, error="m").svg_inline(scale=5, dark="#111111", light="#ffffff", border=2)
    return svg[svg.index("<svg"):]


def _hash(code):
    return hashlib.sha256(code.strip().lower().replace("-", "").replace(" ", "").encode()).hexdigest()


def new_backup_codes():
    codes = ["".join(secrets.choice(_ALPHABET) for _ in range(10)) for _ in range(BACKUP_COUNT)]
    codes = [f"{c[:5]}-{c[5:]}" for c in codes]
    return codes, [_hash(c) for c in codes]


def _clean(code):
    return "".join(str(code or "").split())


def check_totp(secret, code, last_step=0, now=None):
    """Step number when ``code`` is valid now (±1 step) and newer than ``last_step``; else None."""
    code = _clean(code)
    if not secret or not code.isdigit() or len(code) != 6:
        return None
    totp = pyotp.TOTP(secret)
    now = time.time() if now is None else now
    step = int(now // totp.interval)
    for candidate in (step, step - 1, step + 1):
        if candidate > last_step and hmac.compare_digest(totp.generate_otp(candidate), code):
            return candidate
    return None


def verify(user_settings, code, allow_backup=True):
    """Check a TOTP or a backup code for an enabled account; consumes what it uses."""
    if not user_settings.totp_enabled:
        return False
    step = check_totp(user_settings.totp_secret, code, user_settings.totp_last_step)
    if step is not None:
        user_settings.totp_last_step = step
        user_settings.save(update_fields=["totp_last_step"])
        return True
    if allow_backup:
        hashed = _hash(_clean(code))
        codes = list(user_settings.totp_backup_codes or [])
        for stored in codes:
            if hmac.compare_digest(stored, hashed):
                codes.remove(stored)
                user_settings.totp_backup_codes = codes
                user_settings.save(update_fields=["totp_backup_codes"])
                return True
    return False
