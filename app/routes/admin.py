"""
Module routes/master (admin.py)
Rôle:
- Expose des endpoints MJ (Master of the Game) pour suivre les événements et l’activité des sessions.
- Protégé par un guard `mj_required` + vérification Bearer maison `_mj()`.

Intégrations:
- settings.MJ_TOKEN: jeton Bearer attendu côté MJ.
- GAME_STATE: lecture des événements en mémoire (buffer d’events).
- RUNTIME: état runtime des mini-jeux (sessions actives / historiques).
- Déco FastAPI `Depends(mj_required)` pour exiger une auth MJ globale sur le router.

Remarques:
- `_mj()` double la sécurité: on exige `Authorization: Bearer <MJ_TOKEN>`.
- Les routes sont uniquement des lectures (GET) — pas de mutations ici.
"""
from fastapi import APIRouter, Header, HTTPException, Query, Depends
from app.config.settings import settings
from app.services.game_state import GAME_STATE
from app.services.minigame_runtime import RUNTIME
from app.deps.auth import mj_required

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(mj_required)]  # ← garde-fou MJ sur tout le router
)

def _mj(auth: str | None):
    """
    Vérifie explicitement le header Authorization côté MJ.
    Double verrou de sécurité avec `mj_required`.
    """
    if not auth or not auth.startswith("Bearer ") or auth.split(" ",1)[1] != settings.MJ_TOKEN:
        raise HTTPException(status_code=403, detail="MJ auth required")

@router.get("/events")
async def list_events(
    limit: int = Query(100, ge=1, le=1000),
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    """
    Récupère les derniers événements du jeu.
    - `limit`: nombre maximum d'events renvoyés (fenêtrage).
    - Auth: nécessite un Bearer MJ valide.
    """
    _mj(authorization)
    return {"events": GAME_STATE.events[-limit:]}  # ← slice sécurisé

@router.get("/sessions/active")
async def sessions_active(authorization: str | None = Header(default=None, alias="Authorization")):
    """
    Retourne la liste des sessions de mini-jeu actives (si dispo dans RUNTIME).
    """
    _mj(authorization)
    return {"active": RUNTIME.state.get("active", [])}

@router.get("/sessions/history")
async def sessions_history(
    limit: int = Query(100, ge=1, le=1000),
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    """
    Historique des sessions de mini-jeu.
    - On renvoie les `limit` derniers éléments si existants.
    """
    _mj(authorization)
    history = RUNTIME.state.get("history", [])
    return {"history": history[-limit:]}
