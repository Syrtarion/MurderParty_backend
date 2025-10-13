"""
Module routes/master_reveal.py
Rôle:
- Révélation du coupable (déjà défini dans le canon) + distribution des missions.
- Notifie chaque joueur par WS de sa mission secrète.
- Diffuse un signal global "missions_ready" (affichage/état front).

Sécurité:
- Accès MJ uniquement (`mj_required`).

Flux:
1) Lire le canon (NARRATIVE.canon) et récupérer `culprit_player_id`.
2) Validation présence du joueur désigné (toujours en jeu).
3) Marquer `is_culprit=True` côté GAME_STATE.
4) `MISSION_SVC.assign_missions()` : attribution unique/équitable.
5) Envoi WS individuel (missions secrètes), puis broadcast global.
6) Log des événements majeurs.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.deps.auth import mj_required
from app.services.game_state import GAME_STATE
from app.services.narrative_core import NARRATIVE
from app.services.mission_service import MISSION_SVC
from app.services.ws_manager import ws_send_to_player_safe, ws_broadcast_safe

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(mj_required)]
)

@router.post("/reveal_culprit")
async def reveal_culprit():
    """
    Révèle le coupable et assigne les missions à tous les joueurs.
    - Notifie chaque joueur via WS (message "secret_mission").
    - Diffuse "missions_ready" en broadcast.
    """
    canon = NARRATIVE.canon
    culprit_pid = canon.get("culprit_player_id")
    if not culprit_pid:
        raise HTTPException(status_code=400, detail="Aucun coupable défini dans le canon narratif.")

    if culprit_pid not in GAME_STATE.players:
        raise HTTPException(status_code=400, detail="Le joueur coupable n'est pas présent dans la partie.")

    # Marquer l'état du joueur désigné
    GAME_STATE.players[culprit_pid]["is_culprit"] = True

    # Attribution des missions depuis le pool (story_seed.json)
    try:
        assigned = MISSION_SVC.assign_missions()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'attribution des missions : {e}")

    # Envoi des missions à chaque joueur
    for pid, mission in assigned.items():
        ws_send_to_player_safe(pid, {"type": "secret_mission", "mission": mission})

    # Log et diffusion globales
    GAME_STATE.log_event("culprit_revealed", {"culprit_player_id": culprit_pid})
    ws_broadcast_safe({
        "type": "event",
        "kind": "missions_ready",
        "payload": {"count": len(assigned)}
    })
    GAME_STATE.log_event("missions_ready", {"count": len(assigned)})

    return {
        "ok": True,
        "culprit_player_id": culprit_pid,
        "culprit_name": GAME_STATE.players[culprit_pid].get("character") or GAME_STATE.players[culprit_pid].get("display_name"),
        "missions_assigned_count": len(assigned)
    }
