"""
Module routes/timeline.py
Rôle:
- Expose la timeline consolidée (événements publics/privés/admin) depuis le canon.
- Filtre, masque les spoilers, et peut cibler les messages privés d'un joueur.

I/O:
- Lit `app/data/canon_narratif.json` puis récupère `timeline` (list d'objets).

Paramètres:
- scope: "all" | "public" | "private" | "admin" (filtrage par visibilité)
- limit: tronquage sur la fin si défini
- spoiler: si True, masque le contenu pour entries privées/admin
- player_id: garde les privés correspondant au joueur demandé

Robustesse:
- 404 si le fichier n’existe pas.
- 500 si structure invalide ou lecture défaillante.

Front:
- Permet d'afficher un flux "safe" côté joueurs, ou un flux complet côté MJ.
"""
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
    Retourne la timeline filtrée selon les paramètres fournis.
    - `scope` contrôle la visibilité globale.
    - `spoiler=True` masque les textes privés/admin.
    - `player_id` permet d'exposer les entrées privées ciblées.
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
            # seulement les événements strictement privés
            return s == "private"

        elif scope == "admin":
            # accès complet
            return s in ("admin", "private", "public", "broadcast")

        return False

    filtered = [e for e in timeline if visible(e)]

    # --- masquage anti-spoiler ---
    if spoiler:
        for e in filtered:
            if e.get("scope") in ("admin", "private"):
                e["text"] = "🔒 (contenu masqué - spoiler)"

    # --- filtrage par joueur (n'expose que ses privés) ---
    if player_id:
        filtered = [
            e for e in filtered
            if e.get("scope") == "public"
            or e.get("scope") == "broadcast"
            or (e.get("scope") == "private" and e.get("meta", {}).get("player_id") == player_id)
        ]

    # --- limite de résultats (queue) ---
    if limit:
        filtered = filtered[-limit:]

    return {"ok": True, "count": len(filtered), "timeline": filtered}
