"""Sign up, log in, log out, who am I. The landing/login/signup pages call these four endpoints."""
import re
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from . import auth, db
from .common import norm_phone, now

router = APIRouter(prefix="/api/auth", tags=["auth"])
FAILS: dict[str, list[float]] = {}  # in-memory login throttle (fine for one server process)
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupIn(BaseModel):
    name: str
    email: str
    password: str
    role: str                      # "dealer" or "customer"
    phone: str = ""
    business_name: str = ""
    invite_token: str = ""        # from the dealer's /join/<token> link; connects you to their records


class LoginIn(BaseModel):
    email: str
    password: str


def _start(request: Request, response: Response, user: dict) -> dict:
    token = auth.create_session(user["id"])
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/")
    return {**auth.public_user(user), "home": auth.home_for(user)}


@router.post("/signup")
def signup(body: SignupIn, request: Request, response: Response):
    email = body.email.strip().lower()
    if body.role not in auth.ROLES:
        raise HTTPException(400, "Choose dealer or customer")
    if not body.name.strip():
        raise HTTPException(400, "Enter your name")
    if not EMAIL.match(email):
        raise HTTPException(400, "Enter a valid email")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if body.invite_token:
        if body.role != "customer":
            raise HTTPException(400, "Invite links are for customer accounts")
        info = auth.invite_info(body.invite_token)
        if not info:
            raise HTTPException(400, "This invite link is not valid")
        if info["user_id"]:
            raise HTTPException(409, "This invite was already used. Ask the dealer for a new one.")
    salt, h = auth.hash_password(body.password)
    uid = uuid.uuid4().hex[:10]
    try:
        with db.conn() as c:
            c.execute("INSERT INTO users (id,name,email,phone,role,business_name,pw_salt,pw_hash,created) VALUES (?,?,?,?,?,?,?,?,?)",
                      (uid, body.name.strip()[:80], email, norm_phone(body.phone), body.role,
                       body.business_name.strip()[:80], salt, h, now()))
    except Exception:
        raise HTTPException(409, "An account with this email already exists")
    user = auth.current_user_by_id(uid)
    if body.invite_token:
        auth.claim_invite(body.invite_token, user)
    return _start(request, response, user)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    email = body.email.strip().lower()
    recent = [t for t in FAILS.get(email, []) if time.time() - t < 600]
    if len(recent) >= 5:
        raise HTTPException(429, "Too many wrong attempts. Try again in a few minutes.")
    with db.conn() as c:
        r = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not r or not auth.check_password(body.password, r["pw_salt"], r["pw_hash"]):
        FAILS[email] = recent + [time.time()]
        raise HTTPException(401, "Wrong email or password")
    FAILS.pop(email, None)
    return _start(request, response, dict(r))


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE)
    if token:
        auth.end_session(token)
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    user = auth.need_user(request)
    return {**auth.public_user(user), "home": auth.home_for(user)}


join = APIRouter(prefix="/api/join", tags=["auth"])


@join.get("/{token}")
def join_info(token: str):
    """For the signup page: 'Ravi Traders invited you.'"""
    info = auth.invite_info(token)
    if not info or info["user_id"]:
        raise HTTPException(404, "This invite link is not valid or was already used")
    return {"customer_name": info["customer_name"], "dealer_name": info["dealer_name"], "business_name": info["business_name"]}


@join.post("/{token}")
def join_claim(token: str, user: dict = Depends(auth.need_customer)):
    """A customer who already has an account opens the link while logged in."""
    info = auth.claim_invite(token, user)
    return {"ok": True, "dealer_name": info["dealer_name"]}
