"""
Module routes/master_intro.py
Rôle:
- Génère l'introduction publique de la partie (narration d'ouverture),
  tout en produisant/actualisant le "canon narratif" (culprit/lieu/arme/mobile).
- Persiste dans `canon_narratif.json` via le service `narrative_engine`.

Sécurité:
- Router protégé par `mj_required` (réservé au maître du jeu).

Flux:
1) `generate_canon_and_intro(use_llm)` fabrique/charge le canon + intro.
2) On log l'événement "intro_generated" dans GAME_STATE (trace runtime).
3) On renvoie un texte d'intro public (sans spoilers) + chemins utiles.

Notes:
- `use_llm=True`: laisse le service décider s’il appelle le LLM (Ollama, etc.)
- `public_path` → endpoint public à utiliser côté écran/tablette joueurs.
"""
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
    Déclenche la génération de l'introduction (et du canon si absent).
    Retour:
    - `intro_text`: narration publique non spoilante
    - `public_path`: endpoint à consommer par le front public
    - `canon_file`: fichier JSON persisté
    """
    try:
        data = generate_canon_and_intro(use_llm=use_llm)

        # Journalisation côté runtime (diagnostic + audit MJ)
        GAME_STATE.log_event("intro_generated", {
            "location": data["location"],
            "culprit_hint": "hidden"  # on ne divulgue rien ici
        })

        return {
            "ok": True,
            "intro_text": data.get("intro_narrative", ""),
            "public_path": "/public/intro",
            "canon_file": "canon_narratif.json"
        }

    except Exception as e:
        # Renvoyer une 500 lisible pour l'interface MJ
        raise HTTPException(status_code=500, detail=f"Erreur lors de la génération de l’intro: {e}")
