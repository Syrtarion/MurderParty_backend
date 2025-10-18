"""
Dépendances d'authentification MJ (Maître du Jeu)
==================================================

Objectif
--------
Fournir une *dependency* FastAPI `mj_required` qui autorise l'accès MJ via:
1) un **Bearer token** (pratique en dev/CLI), *ou*
2) un **cookie de session HttpOnly** (sécurisé pour l'interface MJ du front).

Intégrations
------------
- `settings.MJ_TOKEN` : token Bearer (dev).
- `GAME_STATE` : stockage persistant des sessions MJ dans `state["__mj_sessions__"]`.
- Cookies : `mj_session` (HttpOnly, SameSite=Lax, Secure en prod).

Pourquoi accepter le préflight CORS ?
-------------------------------------
Le navigateur envoie une requête **OPTIONS** sans header `Authorization`. Il faut donc :
- **laisser passer** les OPTIONS (géré par le middleware CORS),
- et **protéger seulement** les méthodes réelles (GET/POST/...) avec `mj_required`.

API exposée ici
---------------
- `mj_required` : dependency à utiliser sur chaque route **à protéger**.
- `create_mj_session()` / `delete_mj_session()` : helpers utilisés par `/auth/mj/login|logout`.

Comportement & codes retour
---------------------------
- 401 si aucune authentification (ni cookie valide, ni Bearer).
- 403 si Bearer fourni mais invalide.
- True sinon.

Notes
-----
- On garde `HTTPBearer(auto_error=False)` pour faire remonter 401/403 propres.
- Le cookie est vérifié **avant expiration**. Si expiré → supprimé.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any
from uuid import uuid4
from datetime import datetime, timedelta

from app.config.settings import settings
from app.services.game_state import GAME_STATE

# ----------------------------
# Constantes & utilitaires
# ----------------------------
_MJ_COOKIE_NAME = "mj_session"
_MJ_SESS_KEY = "__mj_sessions__"
_MJ_TTL_SECONDS = 12 * 3600  # 12 heures

def _now_ts() -> int:
    return int(datetime.utcnow().timestamp())

def _sessions() -> Dict[str, Any]:
    """Accède (ou crée) le dictionnaire des sessions MJ dans GAME_STATE."""
    return GAME_STATE.state.setdefault(_MJ_SESS_KEY, {})

def create_mj_session() -> str:
    """
    Crée une session MJ avec TTL, la stocke dans GAME_STATE, et renvoie le session_id.
    Utilisé par /auth/mj/login.
    """
    sid = uuid4().hex
    _sessions()[sid] = {"exp": _now_ts() + _MJ_TTL_SECONDS}
    GAME_STATE.save()
    return sid

def delete_mj_session(sid: Optional[str]) -> None:
    """Supprime une session MJ de GAME_STATE et persiste."""
    if not sid:
        return
    store = _sessions()
    if sid in store:
        store.pop(sid, None)
        GAME_STATE.save()

def _cookie_valid(request: Request) -> bool:
    """
    Valide la session MJ par cookie HttpOnly. Retourne True si (sid présent ET non expiré).
    En cas d'expiration, la session est supprimée.
    """
    sid = request.cookies.get(_MJ_COOKIE_NAME)
    if not sid:
        return False
    rec = _sessions().get(sid)
    if not isinstance(rec, dict):
        return False
    if int(rec.get("exp", 0)) < _now_ts():
        delete_mj_session(sid)
        return False
    return True

# Schéma Bearer (désactive l'erreur auto pour qu'on rende nos 401/403)
bearer = HTTPBearer(auto_error=False)

def mj_required(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
):
    """
    Dépendance d'accès MJ.

    Autorise si:
    - Cookie de session MJ valide (HttpOnly), OU
    - Authorization: Bearer <settings.MJ_TOKEN>

    Exceptions:
    - 401 si aucune authentification n'est fournie/valide,
    - 403 si un Bearer est fourni mais ne correspond pas à `MJ_TOKEN`.
    """
    # 1) Cookie HttpOnly (recommandé pour l'interface MJ)
    if _cookie_valid(request):
        return True

    # 2) Bearer (dev/CLI)
    if credentials and (credentials.scheme or "").lower() == "bearer":
        if credentials.credentials == settings.MJ_TOKEN:
            return True
        raise HTTPException(status_code=403, detail="Invalid token")

    # Rien de valide → refus
    raise HTTPException(status_code=401, detail="MJ authentication required")
