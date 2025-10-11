from fastapi import APIRouter, Query, HTTPException
from typing import Optional, Literal
from pathlib import Path
import json

router = APIRouter(prefix="/timeline", tags=["timeline"])

CANON_PATH = Path("app/data/canon_narratif.json")

@router.get("/")
async def get_timeline(
    scope: Literal["all", "public", "private", "admin"] = Query("all"),
    limit: Optional[int] = Query(None, description="Limiter le nombre d'événements"),
    spoiler: bool = Query(False, description="Masquer les entrées spoilantes"),
    player_id: Optional[str] = Query(None, description="Inclure les entrées privées de ce joueur")
):
    """
    Retourne la timeline complète (filtrée si besoin).
    """
    if not CANON_PATH.exists():
        raise HTTPException(status_code=404, detail="Fichier canon_narratif.json introuvable.")

    try:
        with open(CANON_PATH, "r", encoding="utf-8") as f:
            canon = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lecture canon: {e}")

    timeline = canon.get("timeline", [])
    if not isinstance(timeline, list):
        raise HTTPException(status_code=500, detail="Structure timeline invalide.")

    # --- filtrage par scope ---
    def visible(entry):
        s = entry.get("scope", "public")

        if scope == "all":
            return True

        elif scope == "public":
            # uniquement les événements visibles publiquement
            return s in ("public", "broadcast")

        elif scope == "private":
            # seulement les événements strictement privés (et éventuellement filtrés par player_id après)
            return s == "private"

        elif scope == "admin":
            # les admins voient absolument tout
            return s in ("admin", "private", "public", "broadcast")

        return False


    filtered = [e for e in timeline if visible(e)]

    # --- masquage anti-spoiler ---
    if spoiler:
        for e in filtered:
            if e.get("scope") in ("admin", "private"):
                e["text"] = "🔒 (contenu masqué - spoiler)"
    
    # --- filtrage par joueur ---
    if player_id:
        filtered = [
            e for e in filtered
            if e.get("scope") == "public"
            or e.get("scope") == "broadcast"
            or (e.get("scope") == "private" and e.get("meta", {}).get("player_id") == player_id)
        ]

    # --- limite ---
    if limit:
        filtered = filtered[-limit:]

    return {"ok": True, "count": len(filtered), "timeline": filtered}
