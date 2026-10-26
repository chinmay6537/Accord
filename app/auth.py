"""Accounts and sessions. Two roles: "dealer" (creates deals) and "customer" (receives them).

Passwords are hashed with scrypt. The browser holds a random session token in an HttpOnly cookie;
only a SHA-256 of that token is stored, so a leaked database does not leak live sessions.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request

from . import db
from .common import now

COOKIE = "accord_session"
SESSION_DAYS = 14
ROLES = ("dealer", "customer")


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return salt.hex(), h.hex()


def check_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, h = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(h, hash_hex)


def _th(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    with db.conn() as c:
        c.execute("INSERT INTO sessions (token_hash,user_id,created,expires) VALUES (?,?,?,?)",
                  (_th(token), user_id, now(), expires))
    return token


def end_session(token: str):
    with db.conn() as c:
        c.execute("DELETE FROM sessions WHERE token_hash=?", (_th(token),))


def current_user_by_id(user_id: str) -> dict:
    with db.conn() as c:
        return dict(c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


def public_user(u: dict) -> dict:
    return {k: u[k] for k in ("id", "name", "email", "phone", "role", "business_name")}


def current_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    with db.conn() as c:
        r = c.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?",
            (_th(token), now()),
        ).fetchone()
    return dict(r) if r else None


def need_user(request: Request) -> dict:
    u = current_user(request)
    if not u:
        raise HTTPException(401, "Please log in")
    return u


def need_dealer(user: dict = Depends(need_user)) -> dict:
    if user["role"] != "dealer":
        raise HTTPException(403, "Dealers only")
    return user


def need_customer(user: dict = Depends(need_user)) -> dict:
    if user["role"] != "customer":
        raise HTTPException(403, "Customers only")
    return user


def home_for(user: dict) -> str:
    return "/dealer" if user["role"] == "dealer" else "/customer"


def invite_info(token: str) -> dict | None:
    """Who invited this person? Public, and deliberately says very little."""
    with db.conn() as c:
        r = c.execute(
            "SELECT c.id, c.name AS customer_name, c.user_id, u.name AS dealer_name, u.business_name "
            "FROM customers c JOIN users u ON u.id=c.dealer_id WHERE c.invite_token=?", (token,)).fetchone()
    return dict(r) if r else None


def claim_invite(token: str, user: dict):
    """Connect this customer account to the record the dealer made for them. The private link is the proof
    that the dealer meant this person; matching an email or phone number would not be, since neither is verified."""
    if user["role"] != "customer":
        raise HTTPException(400, "Invite links are for customer accounts")
    info = invite_info(token)
    if not info:
        raise HTTPException(404, "This invite link is not valid")
    if info["user_id"] and info["user_id"] != user["id"]:
        raise HTTPException(409, "This invite was already used by someone else. Ask the dealer for a new one.")
    with db.conn() as c:
        c.execute("UPDATE customers SET user_id=? WHERE id=?", (user["id"], info["id"]))
    return info
