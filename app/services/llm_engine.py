"""
Service: llm_engine.py
Rôle:
- Centraliser les appels LLM (Ollama par défaut) pour la génération
  d'indices et de textes (JSON ou phrases courtes).
- Appliquer une post-édition et un anti-spoiler basés sur le canon.

Fonctions:
- generate_indice(prompt, kind): chat LLM (Ollama /api/chat) → 1–2 phrases FR.
- run_llm(prompt): génération brute (Ollama /api/generate) → flux concaténé.

Sécurité narrative:
- `get_canon_summary()` + `get_sensitive_terms()` injectés en system.
- `_has_spoiler()` détecte les confessions ou mentions du canon (regex + banlist).
"""
import requests, re
import json
from typing import Dict, Any, List
from app.config.settings import settings
from app.services.narrative_core import get_canon_summary, get_sensitive_terms, CONFESSION_PATTERNS

SESSION = requests.Session()

SYSTEM_PROMPT = (
    "You are the narrative engine of a live murder mystery role-playing game. "
    "You MUST ALWAYS respond in French. "
    "Generate only short clues (1–2 sentences), atmospheric but concrete, "
    "that never reveal the culprit directly and never contradict the locked canon. "
    "Keep them immersive and diegetic, without meta-language or stage directions."
)


def _truncate_to_two_sentences(text: str) -> str:
    """Coupe proprement la sortie à 1–2 phrases max (délimiteurs .!?)."""
    parts = re.split(r"([\.!?])", text.strip())
    if len(parts) <= 2:
        return text.strip()
    return "".join(parts[:4]).strip()


def _strip_lead_ins(text: str) -> str:
    """Supprime des préambules type 'Indice:' 'Voici un indice:' pour un rendu direct."""
    return re.sub(r"^\s*(?:indice\s*:\s*|voici\s+un\s+indice\s*:\s*)", "", text, flags=re.IGNORECASE).strip()


def _has_spoiler(text: str, sensitive_terms: List[str]) -> bool:
    """Détection heuristique: termes du canon + motifs de confession."""
    low = text.lower()
    for t in sensitive_terms:
        if t and t.lower() in low:
            return True
    for pat in CONFESSION_PATTERNS:
        if pat.search(text):
            return True
    return False


def _postprocess(text: str) -> str:
    """Chaîne de post-traitement (nettoyage préfixe + troncature)."""
    txt = _strip_lead_ins(text)
    txt = _truncate_to_two_sentences(txt)
    return txt.strip()


def generate_indice(prompt: str, kind: str = "ambiguous", temperature: float = 0.7, max_attempts: int = 2) -> Dict[str, Any]:
    """
    Génère un indice via Ollama (/api/chat par défaut) en tenant compte du canon et des garde-fous.
    - `kind` influe la température (crucial/ambiguous/red_herrings/decor).
    - Plusieurs tentatives si spoiler détecté.
    """
    endpoint = settings.LLM_ENDPOINT.replace("/api/generate", "/api/chat")

    canon = get_canon_summary()
    sensitive_terms = get_sensitive_terms()

    temp_by_kind = {"crucial": 0.55, "red_herrings": 0.8, "ambiguous": 0.7, "decor": 0.6}
    t = temp_by_kind.get(kind, temperature)

    base_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": (
            "Canon (private, do not reveal): "
            f"Culprit={canon.get('culprit')}; Weapon={canon.get('weapon')}; "
            f"Location={canon.get('location')}; Motive={canon.get('motive')}."
        )},
        {"role": "system", "content": ("Recent clues summary (private): " f"{canon.get('last_clues')}")},
        {"role": "system", "content": (
            f"Clue type requested: {kind}. Output strictly 1–2 sentences. "
            "Do not name the culprit, do not confess, do not contradict the canon."
        )},
    ]

    attempt, last_err = 0, None
    while attempt <= max_attempts:
        try:
            messages = list(base_messages) + [{"role": "user", "content": prompt}]
            if attempt > 0 and sensitive_terms:
                # Renforcement anti-spoiler aux tentatives suivantes
                banlist = ", ".join(sensitive_terms[:5])
                messages.append({"role": "system", "content": f"Do NOT mention or allude to: {banlist}. Rephrase to avoid spoilers."})

            resp = SESSION.post(
                endpoint,
                json={
                    "model": settings.LLM_MODEL,
                    "messages": messages,
                    "options": {
                        "temperature": t,
                        "top_p": 0.9,
                        "repeat_penalty": 1.15,
                        "num_ctx": 2048,
                    },
                    "stream": False,
                    "keep_alive": "2m",
                },
                timeout=45,
            )
            resp.raise_for_status()
            data = resp.json()
            # Ollama /api/chat peut renvoyer {"message":{"content":...}} ou {"response":...}
            text = (data.get("message") or {}).get("content") or data.get("response") or ""
            text = _postprocess(text)

            if _has_spoiler(text, sensitive_terms):
                attempt += 1
                continue

            return {"text": text, "kind": kind, "attempts": attempt + 1}
        except Exception as e:
            last_err = str(e)
            attempt += 1

    # Fallback minimal en cas d'échecs répétés
    return {"text": f"[stub] {kind} clue based on: {prompt[:120]}...", "kind": kind, "error": last_err or "antispam"}

def run_llm(prompt: str) -> dict:
    """
    Appelle le LLM configuré et retourne un dict { 'text': ... }.
    - Ollama /api/generate renvoie un flux JSONL → concaténation des 'response'.
    - Fallback stub si provider inconnu.
    """
    if settings.LLM_PROVIDER == "ollama":
        url = "http://localhost:11434/api/generate"
        payload = {"model": settings.LLM_MODEL, "prompt": prompt}
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        text = resp.text

        # Ollama stream → concaténation de chaque ligne JSON {"response": "..."}
        out = ""
        for line in text.splitlines():
            try:
                data = json.loads(line)
                out += data.get("response", "")
            except Exception:
                continue
        return {"text": out.strip()}

    # fallback : stub
    return {"text": f"[stub] réponse à partir du prompt: {prompt[:50]}..."}
