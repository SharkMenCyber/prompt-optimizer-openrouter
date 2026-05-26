from __future__ import annotations

import re
import hashlib
import hmac
import secrets
from typing import Any


REDACTED_SECRET = "[REDACTED_SECRET]"
LOCAL_API_KEY_PREFIX = "po"
SESSION_TOKEN_PREFIX = "pos"
INVITATION_TOKEN_PREFIX = "poi"
PASSWORD_RESET_TOKEN_PREFIX = "por"
PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260_000

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(OPENROUTER(?:_[A-Z0-9]+)*_KEY_)[A-Za-z0-9_\-]{12,}\b"),
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,})\b"),
    re.compile(r"\b(ghp_[A-Za-z0-9_]{16,})\b"),
    re.compile(r"\b(github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\b(hf_[A-Za-z0-9_\-]{16,})\b"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{12,}"),
    re.compile(
        r"(?i)\b((?:api|admin|secret|access|refresh|session|auth|private|client)"
        r"[_\-\s]*(?:key|token|secret|password)\s*[:=]\s*)['\"]?[^'\"\s,;]{8,}['\"]?"
    ),
    re.compile(
        r"(?i)\b([A-Z0-9_]*(?:API|ADMIN|SECRET|ACCESS|REFRESH|SESSION|AUTH|PRIVATE)"
        r"[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)?\s*[:=]\s*)[^\s,;]+"
    ),
]

LONG_TOKEN_RE = re.compile(
    r"\b(?=[A-Za-z0-9_\-]{28,}\b)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_\-]{28,}\b"
)


def redact_text(text: str | None) -> str | None:
    if text is None:
        return None

    redacted = str(text)
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(_redact_match, redacted)
    redacted = LONG_TOKEN_RE.sub(_redact_long_token, redacted)
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    return value


def contains_secret(value: Any) -> bool:
    if isinstance(value, str):
        return redact_text(value) != value
    if isinstance(value, dict):
        return any(contains_secret(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_secret(item) for item in value)
    return False


def safe_error_message(error: Exception | str, default: str = "Request failed.") -> str:
    message = redact_text(str(error)) or default
    message = " ".join(message.split())
    if not message:
        return default
    return message[:700]


def create_local_api_key() -> tuple[str, str, str]:
    key = f"{LOCAL_API_KEY_PREFIX}_{secrets.token_urlsafe(32)}"
    return key, visible_key_prefix(key), hash_secret(key)


def create_session_token() -> tuple[str, str, str]:
    token = f"{SESSION_TOKEN_PREFIX}_{secrets.token_urlsafe(48)}"
    return token, visible_key_prefix(token), hash_secret(token)


def create_invitation_token() -> tuple[str, str, str]:
    token = f"{INVITATION_TOKEN_PREFIX}_{secrets.token_urlsafe(36)}"
    return token, visible_key_prefix(token), hash_secret(token)


def create_password_reset_token() -> tuple[str, str, str]:
    token = f"{PASSWORD_RESET_TOKEN_PREFIX}_{secrets.token_urlsafe(48)}"
    return token, visible_key_prefix(token), hash_secret(token)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_secret(secret: str, stored_hash: str) -> bool:
    if not secret or not stored_hash:
        return False
    return hmac.compare_digest(hash_secret(secret), stored_hash)


def visible_key_prefix(secret: str) -> str:
    if len(secret) <= 12:
        return secret
    return f"{secret[:8]}...{secret[-4:]}"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"{PASSWORD_HASH_SCHEME}${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not password or not stored_hash:
        return False
    try:
        scheme, iterations_text, salt, expected = stored_hash.split("$", 3)
        if scheme != PASSWORD_HASH_SCHEME:
            return False
        iterations = int(iterations_text)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def _redact_match(match: re.Match[str]) -> str:
    groups = match.groups()
    if groups:
        prefix = groups[0] or ""
        if match.re.pattern.startswith(r"\b(sk-") or match.re.pattern.startswith(r"\b(ghp_"):
            return REDACTED_SECRET
        if match.re.pattern.startswith(r"\b(github_pat_") or match.re.pattern.startswith(r"\b(hf_"):
            return REDACTED_SECRET
        return f"{prefix}{REDACTED_SECRET}"
    return REDACTED_SECRET


def _redact_long_token(match: re.Match[str]) -> str:
    token = match.group(0)
    if UUID_RE.fullmatch(token):
        return token
    return REDACTED_SECRET
