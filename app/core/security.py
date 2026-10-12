from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import jwt
from pwdlib import PasswordHash

from app.config import settings


SECRET_KEY = settings.secret_key
ALGORITHM = settings.algorithm

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def create_access_token(data: dict) -> str:
    payload = data.copy()

    payload.update({
        "exp": datetime.now(timezone.utc)
        + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
        "jti": str(uuid4()),
    })

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def create_refresh_token(data: dict) -> str:
    payload = data.copy()

    payload.update({
        "exp": datetime.now(timezone.utc)
        + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "type": "refresh",
        "jti": str(uuid4()),
    })

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def hash_refresh_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def get_token_expiry(token: str) -> datetime:
    payload = jwt.decode(
        token,
        SECRET_KEY,
        algorithms=[ALGORITHM],
    )

    return datetime.fromtimestamp(
        payload["exp"],
        tz=timezone.utc,
    )