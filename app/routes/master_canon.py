from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import json
import random
from pathlib import Path

from app.deps.auth import mj_required
from app.services.llm_engine import run_llm
from app.services.narrative_core import NARRATIVE
from app.services.game_state import GAME_STATE

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(mj_required)]
)

SEED_PATH = Path("app/data/story_seed.json")

class CanonRequest(BaseModel):
    style: str | None = None  # ex: "Gothique, dramatique"


def load_seed() -> dict:
    """Charge le contexte narratif de la partie."""
    if SEED_PATH.exists():
        try:
            with open(SEED_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


@router.post("/generate_canon")
async def generate_canon(p: CanonRequest):
    """
    Génère automatiquement un canon narratif :
    - Arme, lieu et mobile générés par le LLM
    - Coupable tiré au hasard parmi les joueurs
    """
    seed = load_seed()

    prompt = f"""
    Tu es le moteur narratif d'une Murder Party.

    Contexte de l'histoire :
    Cadre : {seed.get("setting", "Un manoir mystérieux.")}
    Situation : {seed.get("context", "Un dîner qui tourne mal.")}
    Victime : {seed.get("victim", "Un notable local.")}
    Ton : {p.style or seed.get("tone", "Dramatique, réaliste")}.

    Génère uniquement les éléments narratifs suivants au format JSON :
    {{
      "weapon": "<arme du crime>",
      "location": "<lieu du crime>",
      "motive": "<mobile du crime>"
    }}

    Contrainte : renvoie uniquement un JSON valide sans commentaire ni texte hors JSON.
    """

    try:
        # ---- Génération par LLM ----
        result = run_llm(prompt)
        text = result.get("text", "").strip()

        try:
            canon = json.loads(text)
        except json.JSONDecodeError:
            # fallback naïf : extraire le JSON entre {}
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                canon = json.loads(text[start:end+1])
            else:
                raise

        # ---- Tirage du coupable parmi les joueurs ----
        if not GAME_STATE.players:
            raise HTTPException(status_code=400, detail="Aucun joueur inscrit, impossible de désigner un coupable.")

        culprit_id, culprit_data = random.choice(list(GAME_STATE.players.items()))
        culprit_name = culprit_data.get("character") or culprit_data.get("display_name") or culprit_id

        canon["culprit_player_id"] = culprit_id
        canon["culprit_name"] = culprit_name
        canon["locked"] = True

        # ---- Sauvegarde ----
        NARRATIVE.canon = canon
        NARRATIVE.save()

        GAME_STATE.log_event("canon_locked", {
            "weapon": canon["weapon"],
            "location": canon["location"],
            "motive": canon["motive"],
            "culprit_player_id": culprit_id
        })

        return {"ok": True, "canon": canon}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur LLM ou logique canon: {e}")
