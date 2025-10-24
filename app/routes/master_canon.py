"""
Module routes/master_canon.py
Rôle:
- Génère automatiquement un "canon narratif" (arme/lieu/mobile) via LLM
  et verrouille un coupable parmi les joueurs inscrits.

Intégrations:
- run_llm: exécution brute du prompt (retour texte).
- NARRATIVE: stockage du canon + sauvegarde persistante.
- GAME_STATE: sélection d’un joueur au hasard comme coupable + logs d’events.
- register_event: écrit dans la timeline publique.

Robustesse JSON:
- Extraction tolerant aux débordements de texte (cherche { ... }).
- 400 si aucun joueur inscrit (impossible de désigner un coupable).

MISE À JOUR:
- Recopie aussi le canon dans GAME_STATE.state["canon"] pour un accès direct par /party/roles_assign.
"""
# app/routes/master_canon.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import json
import random
from pathlib import Path

from app.deps.auth import mj_required
from app.services.llm_engine import run_llm
from app.services.narrative_core import NARRATIVE
from app.services.game_state import GAME_STATE, register_event

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(mj_required)]
)

SEED_PATH = Path("app/data/story_seed.json")


class CanonRequest(BaseModel):
    style: str | None = None  # ex: "Gothique, dramatique"


def load_seed() -> dict:
    """
    Charge le `story_seed.json` si présent.
    Permet d’injecter un cadre (setting/context/victim/tone) dans le prompt LLM.
    """
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
    - Arme, lieu et mobile par LLM
    - Coupable tiré au hasard parmi les joueurs
    - Verrouille `locked=True` et persiste dans `NARRATIVE` (+ miroir dans GAME_STATE.state["canon"])
    """
    seed = load_seed()

    prompt = f"""
    Tu es le moteur narratif d'une Murder Party.

    Contexte :
    Cadre : {seed.get("setting", "Un manoir mystérieux.")}
    Situation : {seed.get("context", "Un dîner qui tourne mal.")}
    Victime : {seed.get("victim", "Un notable local.")}
    Ton : {p.style or seed.get("tone", "Dramatique, réaliste")}.

    Génère STRICTEMENT ce JSON :
    {{
      "weapon": "<arme du crime>",
      "location": "<lieu du crime>",
      "motive": "<mobile du crime>"
    }}
    """

    try:
        result = run_llm(prompt)
        text = result.get("text", "").strip()

        # --- Parsing JSON robuste ---
        try:
            canon = json.loads(text)
        except json.JSONDecodeError:
            # On tente d’isoler le premier bloc JSON valide
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                canon = json.loads(text[start:end+1])
            else:
                raise

        # --- Sélection d'un coupable parmi les joueurs ---
        if not GAME_STATE.players:
            raise HTTPException(status_code=400, detail="Aucun joueur inscrit, impossible de désigner un coupable.")

        culprit_id, culprit_data = random.choice(list(GAME_STATE.players.items()))
        culprit_name = culprit_data.get("character") or culprit_data.get("display_name") or culprit_id

        # Enrichissement + verrou
        canon["culprit_player_id"] = culprit_id
        canon["culprit_name"] = culprit_name
        canon["locked"] = True

        # Sauvegarde principale
        NARRATIVE.canon = canon
        NARRATIVE.save()

        # Miroir dans GAME_STATE.state["canon"] pour un accès direct par /party/roles_assign
        GAME_STATE.state["canon"] = canon
        GAME_STATE.save()

        # Logs/timeline
        register_event("canon_generated", {
            "weapon": canon.get("weapon"),
            "location": canon.get("location"),
            "motive": canon.get("motive")
        })
        GAME_STATE.log_event("canon_locked", {
            "weapon": canon["weapon"],
            "location": canon["location"],
            "motive": canon["motive"],
            "culprit_player_id": culprit_id
        })

        return {"ok": True, "canon": canon}

    except Exception as e:
        # Remonte une 500 explicite pour le front MJ
        raise HTTPException(status_code=500, detail=f"Erreur LLM ou logique canon: {e}")
