"""
Service: objective_service.py
Rôle:
- Attribuer des points quand un joueur accomplit un objectif.

Intégrations:
- GAME_STATE: mise à jour du profil joueur (objectifs accomplis + score_total).

Notes:
- Idempotent: si l’objectif est déjà dans `objectives_done`, pas de double comptage.
"""
from app.services.game_state import GAME_STATE

DEFAULT_OBJECTIVE_POINTS = 10

def award_objective(player_id: str, objective: str, points: int = DEFAULT_OBJECTIVE_POINTS):
    """Marque un objectif comme accompli pour un joueur et crédite des points."""
    player = GAME_STATE.players.get(player_id)
    if not player:
        # surfacer une ValueError → convertie en 404 côté route
        raise ValueError(f"Player {player_id} not found")

    done = player.setdefault("objectives_done", [])
    if objective not in done:
        done.append(objective)
        player["score_total"] = player.get("score_total", 0) + points
        GAME_STATE.save()
    return {
        "player_id": player_id,
        "score_total": player.get("score_total", 0),
        "objectives_done": done,
    }
