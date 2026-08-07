"""Beheerders-backend: login, repeaterbeheer, API-tokens, wachtwoord."""
import time

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import auth, config, db
from .templating import templates

router = APIRouter(prefix="/admin")


def current_user(request: Request) -> str | None:
    return auth.read_session(request.cookies.get(auth.SESSION_COOKIE))


def require_login(request: Request) -> str:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    return user


def check_csrf(request: Request, csrf: str):
    cookie = request.cookies.get(auth.SESSION_COOKIE, "")
    if not cookie or csrf != auth.csrf_token(cookie):
        raise HTTPException(403, "CSRF-controle mislukt")


def _secure(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "admin/login.html", {
        "site_name": config.SITE_NAME, "error": None,
    })


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    row = db.qone("SELECT * FROM admins WHERE username=?", (username.strip(),))
    if not row or not auth.verify_password(password, row["pw_hash"]):
        time.sleep(1)  # vertraag brute force
        return templates.TemplateResponse(request, "admin/login.html", {
            "site_name": config.SITE_NAME, "error": "Ongeldige inloggegevens",
        }, status_code=401)
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(
        auth.SESSION_COOKIE, auth.make_session(row["username"]),
        max_age=auth.SESSION_TTL, httponly=True, samesite="lax", secure=_secure(request),
    )
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(auth.SESSION_COOKIE)
    return resp


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, new_token: str | None = None):
    user = require_login(request)
    repeaters = db.q("SELECT * FROM repeaters ORDER BY sort_order, name")
    tokens = db.q("SELECT * FROM tokens WHERE revoked=0 ORDER BY created_at")
    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "site_name": config.SITE_NAME, "user": user,
        "repeaters": repeaters, "tokens": tokens,
        "csrf": auth.csrf_token(request.cookies.get(auth.SESSION_COOKIE, "")),
        "new_token": new_token,
    })


@router.post("/repeaters/{rid}/toggle")
def toggle_repeater(request: Request, rid: int, csrf: str = Form(...)):
    require_login(request)
    check_csrf(request, csrf)
    db.execute("UPDATE repeaters SET is_public = 1 - is_public WHERE id=?", (rid,))
    return RedirectResponse("/admin", status_code=303)


@router.post("/repeaters/{rid}/rename")
def rename_repeater(request: Request, rid: int, name: str = Form(...), csrf: str = Form(...)):
    require_login(request)
    check_csrf(request, csrf)
    name = name.strip()
    if name:
        db.execute("UPDATE repeaters SET name=? WHERE id=?", (name, rid))
    return RedirectResponse("/admin", status_code=303)


@router.post("/repeaters/{rid}/delete")
def delete_repeater(request: Request, rid: int, csrf: str = Form(...)):
    require_login(request)
    check_csrf(request, csrf)
    db.execute("DELETE FROM samples WHERE repeater_id=?", (rid,))
    db.execute("DELETE FROM latest WHERE repeater_id=?", (rid,))
    db.execute("DELETE FROM neighbors WHERE repeater_id=?", (rid,))
    db.execute("DELETE FROM repeaters WHERE id=?", (rid,))
    return RedirectResponse("/admin", status_code=303)


@router.post("/tokens")
def create_token(request: Request, name: str = Form(...), csrf: str = Form(...)):
    require_login(request)
    check_csrf(request, csrf)
    token = auth.create_token(name.strip() or "token")
    # Token éénmalig tonen via querystring van de redirect
    return RedirectResponse(f"/admin?new_token={token}", status_code=303)


@router.post("/tokens/{tid}/revoke")
def revoke_token(request: Request, tid: int, csrf: str = Form(...)):
    require_login(request)
    check_csrf(request, csrf)
    db.execute("UPDATE tokens SET revoked=1 WHERE id=?", (tid,))
    return RedirectResponse("/admin", status_code=303)


@router.post("/password")
def change_password(request: Request, current: str = Form(...),
                    new: str = Form(...), csrf: str = Form(...)):
    user = require_login(request)
    check_csrf(request, csrf)
    row = db.qone("SELECT * FROM admins WHERE username=?", (user,))
    if not row or not auth.verify_password(current, row["pw_hash"]):
        raise HTTPException(403, "Huidig wachtwoord onjuist")
    if len(new) < 8:
        raise HTTPException(422, "Nieuw wachtwoord moet minstens 8 tekens zijn")
    db.execute("UPDATE admins SET pw_hash=? WHERE id=?", (auth.hash_password(new), row["id"]))
    return RedirectResponse("/admin", status_code=303)
