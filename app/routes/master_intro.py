from fastapi import APIRouter, Depends, HTTPException
from app.deps.auth import mj_required
from app.services.narrative_engine import generate_canon_and_intro
from app.services.game_state import GAME_STATE

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(mj_required)]
)

@router.post("/intro")
async def generate_intro(use_llm: bool = True):
    """
    🔒 Génère et diffuse l’introduction de la partie.
    - Utilise le story_seed.json
    - Produit le canon narratif
    - Sauvegarde dans canon_narratif.json
    - Retourne le texte narratif public (sans spoiler)
    """
    try:
        data = generate_canon_and_intro(use_llm=use_llm)

        GAME_STATE.log_event("intro_generated", {
            "location": data["location"],
            "culprit_hint": "hidden"
        })

        return {
            "ok": True,
            "intro_text": data.get("intro_narrative", ""),
            "public_path": "/public/intro",
            "canon_file": "canon_narratif.json"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la génération de l’intro: {e}")
