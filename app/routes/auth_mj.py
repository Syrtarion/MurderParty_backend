"""
Routes d'authentification MJ (Maître du Jeu)
============================================

Objectif
--------
Offrir un mécanisme d'auth pour l'interface MJ basé sur **cookie HttpOnly** :
- POST /auth/mj/login  : vérifie les identifiants MJ et POSE un cookie 'mj_session'
- POST /auth/mj/logout : supprime la session côté serveur + EFFACE le cookie client

Raisons & sécurité
------------------
- Le cookie est **HttpOnly** : inaccessible au JavaScript → réduit les risques XSS.
- `SameSite="lax"` : empêche la plupart des envois cross-site → atténue CSRF.
- `Secure=True` en PROD (DEBUG=False) : transmis uniquement via HTTPS.
- Les routes protégées utilisent ensuite `Depends(mj_required)` qui accepte
  **soit** ce cookie **soit** un Bearer (pratique pour dev/CLI).

Flux typique côté front
-----------------------
1) L'écran de login MJ POSTe `username/password` à /auth/mj/login **avec** `credentials: "include"`.
   - Le backend répond `{"ok": true}` et **pose** le cookie 'mj_session'.
2) Toutes les requêtes MJ suivantes (ex: /party/status) se font avec `credentials: "include"`,
   sans Bearer → le cookie suffit.
3) /auth/mj/logout permet d'invalider la session et d'effacer le cookie.

Configuration attendue
----------------------
- `settings.MJ_USER`      : login MJ
- `settings.MJ_PASSWORD`  : mot de passe MJ
- `settings.DEBUG`        : True en dev → cookie non `Secure`. False en prod → `Secure`.

Dépendances internes
--------------------
- `create_mj_session` / `delete_mj_session` : gèrent les sessions dans `GAME_STATE`.
- Constantes `_MJ_COOKIE_NAME` et `_MJ_TTL_SECONDS` : nom du cookie et durée de vie.

Remarques
---------
- Cette auth n'implémente pas de CSRF token explicite. Pour une console MJ,
  `SameSite=Lax` + HttpOnly + pas de formulaires cross-site suffisent généralement.
  On peut ajouter un CSRF token applicatif plus tard si besoin.
"""

from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel

from app.config.settings import settings
from app.deps.auth import (
    create_mj_session,
    delete_mj_session,
    _MJ_COOKIE_NAME,
    _MJ_TTL_SECONDS,
)

router = APIRouter(prefix="/auth/mj", tags=["auth"])

class MjLogin(BaseModel):
    username: str
    password: str

@router.post("/login")
def mj_login(p: MjLogin, response: Response):
    """
    Authentifie le MJ (username/password) et pose un cookie HttpOnly 'mj_session'.

    Body:
    - username : doit correspondre à `settings.MJ_USER`
    - password : doit correspondre à `settings.MJ_PASSWORD`

    Réponse:
    - { "ok": true, "ttl": <seconds> }

    Cookies posés:
    - 'mj_session' : HttpOnly, SameSite=Lax, Secure=True si DEBUG=False, durée = _MJ_TTL_SECONDS

    Codes:
    - 401 si credentials invalides
    """
    if p.username != getattr(settings, "MJ_USER", None) or p.password != getattr(settings, "MJ_PASSWORD", None):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    sid = create_mj_session()
    response.set_cookie(
        key=_MJ_COOKIE_NAME,
        value=sid,
        httponly=True,
        samesite="lax",
        secure=(not getattr(settings, "DEBUG", True)),
        max_age=_MJ_TTL_SECONDS,
        path="/",
    )
    return {"ok": True, "ttl": _MJ_TTL_SECONDS}

@router.post("/logout")
def mj_logout(request: Request, response: Response):
    """
    Déconnecte le MJ : supprime la session côté serveur et efface le cookie côté client.

    Réponse:
    - { "ok": true }
    """
    sid = request.cookies.get(_MJ_COOKIE_NAME)
    delete_mj_session(sid)
    response.delete_cookie(_MJ_COOKIE_NAME, path="/")
    return {"ok": True}
