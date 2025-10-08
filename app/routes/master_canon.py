from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import json
import random
from pathlib import Path

from app.deps.auth import mj_required
from app.services.llm_engine import run_llm
from app.services.narrative_core import NARRATIVE
from app.services.game_state import GAME_STATE
from app.services.narrative_engine import generate_canon_and_intro  # pour ton endpoint combiné
from app.services.ws_manager import ws_broadcast_safe

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(mj_required)]
)

SEED_PATH = Path("app/data/story_seed.json")
CANON_PATH = Path("app/data/canon_narratif.json")


# ====================================================
# 🔹 1. GÉNÉRATION DU CANON NARRATIF SEUL
# ====================================================

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
        result = run_llm(prompt)
        text = result.get("text", "").strip()

        try:
            canon = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                canon = json.loads(text[start:end+1])
            else:
                raise

        # Tirage du coupable parmi les joueurs
        if not GAME_STATE.players:
            raise HTTPException(status_code=400, detail="Aucun joueur inscrit, impossible de désigner un coupable.")

        culprit_id, culprit_data = random.choice(list(GAME_STATE.players.items()))
        culprit_name = culprit_data.get("character") or culprit_data.get("display_name") or culprit_id

        canon["culprit_player_id"] = culprit_id
        canon["culprit_name"] = culprit_name
        canon["locked"] = True

        # Sauvegarde
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


# ====================================================
# 🔹 2. GÉNÉRATION DU CANON + INTRO (ta version combinée)
# ====================================================

@router.post("/generate_canon_with_intro")
async def generate_canon_with_intro():
    """
    Génère un canon narratif complet + l'introduction immersive.
    """
    try:
        result = generate_canon_and_intro()
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur génération canon + intro: {e}")


# ====================================================
# 🔹 3. GÉNÉRATION UNIQUEMENT DE L’INTRO
# ====================================================

@router.post("/intro")
async def generate_intro():
    """
    Génère et diffuse la narration d’introduction à partir du canon verrouillé.
    """
    try:
        if not CANON_PATH.exists():
            raise HTTPException(status_code=404, detail="Canon narratif introuvable")

        with open(CANON_PATH, "r", encoding="utf-8") as f:
            canon = json.load(f)

        weapon = canon.get("weapon", "une arme mystérieuse")
        location = canon.get("location", "un lieu inconnu")
        motive = canon.get("motive", "un mobile flou")
        tone = canon.get("tone", "dramatique, immersif")
        victim = canon.get("victim", "la victime")
        culprit = canon.get("culprit_name", "l’un des invités")

        prompt = f"""
        Tu es le narrateur d'une Murder Party.

        Contexte :
        - Lieu du crime : {location}
        - Arme : {weapon}
        - Mobile : {motive}
        - Victime : {victim}
        - Ton : {tone}

        Tâche :
        Rédige une courte introduction immersive (4-6 phrases maximum) pour ouvrir la soirée.
        Elle doit évoquer l’ambiance, le drame, et installer le mystère, sans révéler le coupable.

        Réponds avec un texte brut, sans balise, sans JSON.
        """

        res = run_llm(prompt)
        intro_text = (res.get("text") or "").strip()

        entry = {
            "event": "intro",
            "text": intro_text,
            "scope": "broadcast",
        }
        canon.setdefault("timeline", []).append(entry)

        with open(CANON_PATH, "w", encoding="utf-8") as f:
            json.dump(canon, f, ensure_ascii=False, indent=2)

        # Diffusion WS
        ws_broadcast_safe({
            "type": "narration",
            "scope": "broadcast",
            "payload": {
                "event": "intro",
                "text": intro_text
            }
        })

        return {
            "ok": True,
            "intro_text": intro_text,
            "public_path": "/public/intro",
            "canon_file": "canon_narratif.json"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
