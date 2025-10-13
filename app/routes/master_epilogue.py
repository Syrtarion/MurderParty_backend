"""
Module routes/master_epilogue.py
Rôle:
- Génère un épilogue final (public + privés par joueur) en s’appuyant sur:
  - le canon narratif (arme/lieu/mobile/coupable),
  - un verdict (si présent),
  - un style demandé,
  - la performance des joueurs.

Intégrations:
- run_llm: génère le texte d’épilogue (format JSON).
- NARRATIVE: stockage et timeline (ajout d’un event).
- ws_broadcast_safe: diffusion d’un résumé aux clients (évite exceptions WS).
- register_event: injecte un résumé public dans la timeline.
- Fichiers: lit/écrit canon_narratif.json, verdict.json, epilogue.json.

Robustesse JSON:
- Plusieurs passes pour extraire un JSON valide (guillemets simples, bornes { }).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pathlib import Path
import json

from app.deps.auth import mj_required
from app.services.llm_engine import run_llm
from app.services.narrative_core import NARRATIVE
from app.services.ws_manager import ws_broadcast_safe
from app.services.game_state import register_event

router = APIRouter(
    prefix="/master",
    tags=["master"],
    dependencies=[Depends(mj_required)]
)

# =====================
# 🔹 Modèles
# =====================

class EpilogueRequest(BaseModel):
    style: str | None = None  # Ex: "tragique", "ironique", "romantique"
    personalized: bool = True  # Si True → un message différent pour chaque joueur


# =====================
# 🔹 Fonction principale
# =====================

@router.post("/epilogue")
async def generate_epilogue(req: EpilogueRequest):
    """
    Génère un épilogue final basé sur :
    - Le canon narratif (arme, lieu, mobile, coupable)
    - Les résultats du verdict
    - Le ton demandé (tragique, ironique...)
    - Et la performance des joueurs

    Sortie:
    - Écrit `epilogue.json`
    - Met à jour `canon_narratif.json` avec une clé `epilogue`
    - Ajoute un événement `epilogue` dans la timeline
    - Broadcast un résumé via WS
    """
    canon_path = Path("app/data/canon_narratif.json")
    verdict_path = Path("app/data/verdict.json")
    epilogue_path = Path("app/data/epilogue.json")

    # --- Charger le canon narratif ---
    if not canon_path.exists():
        raise HTTPException(status_code=404, detail="Canon narratif introuvable.")
    canon = json.loads(canon_path.read_text(encoding="utf-8"))

    # --- Charger les résultats du verdict (optionnel) ---
    verdict = {}
    if verdict_path.exists():
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))

    # === Construction du prompt LLM ===
    prompt = f"""
Tu es un narrateur de fin d'enquête.

Donne un épilogue immersif qui conclut la Murder Party.
- Récapitule la vérité : l'arme ({canon.get("weapon")}), le lieu ({canon.get("location")}), le mobile ({canon.get("motive")}) et le coupable ({canon.get("culprit_name")}).
- Mentionne subtilement les réussites et erreurs du groupe selon le verdict global.
- Donne une conclusion émotionnelle avec un ton {req.style or "dramatique"}.
- Ne mentionne jamais de métadonnées techniques.

Retourne uniquement un JSON valide :
{{
  "public_epilogue": "<texte de conclusion collective>",
  "private_epilogues": {{
    "player_id_1": "<texte personnalisé>",
    "player_id_2": "<texte personnalisé>"
  }}
}}
"""

    # --- Exécution du LLM ---
    try:
        result = run_llm(prompt)
        text = (result.get("text") or "").strip()

        # 🔹 Extraction JSON robuste
        epilogue_data = None
        try:
            epilogue_data = json.loads(text)
        except json.JSONDecodeError:
            # Essai 2: remplacer les quotes simples par des doubles
            text_fixed = text.replace("'", '"')  # conversion guillemets simples → doubles
            try:
                epilogue_data = json.loads(text_fixed)
            except Exception:
                # Essai 3: isoler la première zone { ... }
                start, end = text.find("{"), text.rfind("}")
                if start >= 0 and end > start:
                    raw = text[start:end+1].replace("'", '"')
                    epilogue_data = json.loads(raw)
                else:
                    # On renvoie une 500 explicite avec un extrait du texte
                    raise HTTPException(status_code=500, detail=f"Erreur JSON LLM: {text[:200]}")

        if not isinstance(epilogue_data, dict):
            raise HTTPException(status_code=500, detail="Format de réponse LLM invalide.")

        # --- Enregistrement fichier de sortie ---
        epilogue_path.write_text(json.dumps(epilogue_data, indent=2, ensure_ascii=False), encoding="utf-8")

        # --- Ajouter dans la timeline (résumé public) ---
        event = register_event("epilogue", {
            "style": req.style or "dramatique",
            "summary": epilogue_data.get("public_epilogue", "")[:200]
        }, scope="public")

        # --- Diffusion WS (tablette + joueurs) ---
        ws_broadcast_safe({
            "type": "epilogue",
            "data": {
                "public": epilogue_data.get("public_epilogue"),
                "private_count": len(epilogue_data.get("private_epilogues", {}))
            }
        })

        # --- Mise à jour du canon narratif ---
        canon["epilogue"] = epilogue_data
        canon_path.write_text(json.dumps(canon, indent=2, ensure_ascii=False), encoding="utf-8")

        # (Bloc dupliqué conservé: pas de modif logique — n’ajoute qu’un overwrite idempotent)
        canon["epilogue"] = epilogue_data
        canon_path.write_text(json.dumps(canon, indent=2, ensure_ascii=False), encoding="utf-8")

        # --- Ajout sécurisé dans la timeline (mémoire) ---
        if not hasattr(NARRATIVE, "timeline"):
            NARRATIVE.timeline = []
        NARRATIVE.timeline.append(event)
        NARRATIVE.save()

        return {
            "ok": True,
            "public_epilogue": epilogue_data.get("public_epilogue"),
            "private_epilogues": epilogue_data.get("private_epilogues", {})
        }

    except Exception as e:
        # Erreurs attrapées: pb LLM, parse JSON, IO fichiers, etc.
        raise HTTPException(status_code=500, detail=f"Erreur génération épilogue: {e}")
