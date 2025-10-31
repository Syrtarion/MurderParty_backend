"""
Service: narrative_engine.py
Rôle:
- Générer un "canon" minimal (coupable/arme/lieu/mobile) à partir de story_seed.json,
  puis produire une narration d'introduction (via LLM ou fallback offline).
- Persister le résultat dans app/data/canon_narratif.json.

Intégrations:
- run_llm(): moteur LLM (Ollama par défaut) pour l'intro.
- save_json(): helper générique (services.game_state) pour l'écriture JSON.

Notes:
- Le choix aléatoire respecte les contraintes `canon_constraints` du seed.
- `generate_canon_and_intro(use_llm)` est le point d’entrée principal utilisé par /master/intro.
"""
import json
import random
from pathlib import Path
from app.services.llm_engine import run_llm
from app.services.game_state import save_json

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
STORY_SEED_PATH = DATA_DIR / "story_seed.json"
CANON_PATH = DATA_DIR / "canon_narratif.json"


def load_story_seed() -> dict:
    """Charge le fichier story_seed.json et surface des erreurs lisibles."""
    try:
        with open(STORY_SEED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        # chemin abs → utile en dev pour diagnostiquer la config DATA_DIR
        raise FileNotFoundError(f"story_seed.json introuvable à {STORY_SEED_PATH}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Erreur JSON dans story_seed.json : {e}")


def generate_random_canon(seed_data: dict) -> dict:
    """
    Sélectionne aléatoirement le coupable, l'arme, le lieu et le mobile
    en se basant sur les contraintes du story_seed.
    """
    characters = seed_data.get("characters", [])
    constraints = seed_data.get("canon_constraints", {})

    if not characters:
        raise ValueError("Aucun personnage défini dans story_seed.json")

    # Choix aléatoires dans les ensembles proposés
    culprit = random.choice(characters)
    possible_weapons = constraints.get("possible_weapons") or ["Un chandelier"]
    possible_locations = constraints.get("possible_locations") or ["le salon"]
    possible_motives = constraints.get("possible_motives") or ["jalousie"]

    weapon = random.choice(possible_weapons)
    location = random.choice(possible_locations)
    motive = random.choice(possible_motives)

    canon = {
        "culprit": culprit["name"],
        "weapon": weapon,
        "location": location,
        "motive": motive,
        "timestamp": None,  # réservé si on veut marquer l'heure du crime
    }
    return canon


def generate_intro_narrative(canon: dict, seed_data: dict, use_llm: bool = True) -> str:
    """
    Crée une narration d’introduction basée sur le canon.
    Si use_llm=True, génère le texte via le modèle LLM configuré (Ollama).
    """
    setting = seed_data.get("setting", {})
    meta = seed_data.get("meta", {})

    # Contexte injecté au prompt pour guider le style/ton
    context = (
        f"L'histoire se déroule dans {setting.get('location', 'un lieu inconnu')} "
        f"pendant les {setting.get('epoch', 'années indéterminées')}. "
        f"Le ton doit être {meta.get('llm_directives', {}).get('tone', 'mystérieux et dramatique')}."
    )

    prompt = (
        f"{context}\n\n"
        f"Un crime vient d'être commis au {canon['location']}. "
        f"La victime est retrouvée morte, probablement tuée par {canon['weapon']}. "
        f"Le mobile supposé est : {canon['motive']}. "
        f"Le principal suspect pour l'instant est {canon['culprit']}.\n\n"
        "Écris une introduction narrative en français, immersive, courte (5 phrases max), "
        "qui pose l'ambiance sans révéler trop d'éléments du mystère."
    )

    if use_llm:
        # Appel LLM direct (réponse potentiellement multi-lignes)
        result = run_llm(prompt)
        text = result.get("text", "").strip()
        if not text:
            text = "[Erreur LLM] Aucune réponse reçue."
    else:
        # Mode offline / sans LLM (fallback déterministe)
        text = (
            f"Un orage gronde au-dessus du manoir. "
            f"Au matin, le corps d’Henri Delmare est retrouvé dans la {canon['location'].lower()}. "
            f"Une trace de {canon['weapon'].lower()} laisse présager un drame. "
            f"Les invités, déconcertés, cherchent à comprendre le mobile de cette affaire — "
            f"{canon['motive'].lower()}. "
            f"Les soupçons commencent à se porter sur {canon['culprit']}."
        )

    return text


def generate_canon_and_intro(use_llm: bool = True) -> dict:
    """
    Génère le canon complet (culprit, weapon, location, motive)
    + narration d’introduction (LLM ou mode offline).
    Sauvegarde dans canon_narratif.json.
    """
    seed = load_story_seed()
    canon = generate_random_canon(seed)
    intro_text = generate_intro_narrative(canon, seed, use_llm=use_llm)

    # Ajout de l'intro dans le même fichier canon
    canon["intro_narrative"] = intro_text
    save_json(CANON_PATH, canon)
    return canon


# --- Exemple d’utilisation directe ---
if __name__ == "__main__":
    print(">> Génération du canon narratif...")
    data = generate_canon_and_intro(use_llm=False)
    print(json.dumps(data, indent=2, ensure_ascii=False))
