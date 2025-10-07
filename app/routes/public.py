from fastapi import APIRouter, HTTPException
from pathlib import Path
import json

router = APIRouter(prefix="/public", tags=["public"])

CANON_PATH = Path("app/data/canon_narratif.json")

@router.get("/intro")
async def get_public_intro():
    """
    Récupère uniquement la narration publique (intro ou transition).
    Ne contient aucun spoiler.
    Utilisé par la tablette principale ou l’écran collectif.
    """
    if not CANON_PATH.exists():
        raise HTTPException(status_code=404, detail="Aucun canon narratif encore généré.")
    
    try:
        with open(CANON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        raise HTTPException(status_code=500, detail="Erreur de lecture du fichier canon_narratif.json.")

    return {
        "ok": True,
        "intro_text": data.get("intro_narrative", "Aucune narration disponible."),
        "has_spoilers": False
    }
