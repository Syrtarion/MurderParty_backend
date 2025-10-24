"""
Service: llm_engine.py
- Centralise les appels vers le LLM (Ollama par défaut) pour produire indices et textes courts.
- Applique un post-traitement et un filtre anti-spoiler basé sur le canon.

Fonctions principales:
- generate_indice(prompt, kind): appels chat (Ollama /api/chat) avec contrôle spoiler.
- run_llm(prompt): génération brute (Ollama /api/generate) pour les textes JSON.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.config.settings import settings
from app.services.narrative_core import get_canon_summary, get_sensitive_terms, CONFESSION_PATTERNS

logger = logging.getLogger(__name__)

DEFAULT_CHAT_TIMEOUT: Tuple[float, float] = (5.0, 45.0)  # connect, read
DEFAULT_GENERATE_TIMEOUT: Tuple[float, float] = (5.0, 60.0)  # connect, read


class LLMServiceError(RuntimeError):
    """Erreur encapsulant un échec de communication avec le LLM."""


class LLMClient:
    """
    Client HTTP centralisé pour communiquer avec le LLM.
    - Configure retries avec backoff exponentiel.
    - Journalise chaque requête avec un identifiant de corrélation.
    """

    def __init__(
        self,
        chat_endpoint: str,
        *,
        session: Optional[requests.Session] = None,
        chat_timeout: Tuple[float, float] = DEFAULT_CHAT_TIMEOUT,
        generate_timeout: Tuple[float, float] = DEFAULT_GENERATE_TIMEOUT,
    ) -> None:
        self.chat_endpoint = chat_endpoint
        self.generate_endpoint = self._resolve_generate_endpoint(chat_endpoint)
        self.session = session or self._build_session()
        self.chat_timeout = chat_timeout
        self.generate_timeout = generate_timeout

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    @staticmethod
    def _resolve_generate_endpoint(chat_endpoint: str) -> str:
        if chat_endpoint.endswith("/api/chat"):
            return chat_endpoint[:-9] + "generate"
        if chat_endpoint.endswith("/api/chat/"):
            return chat_endpoint[:-10] + "generate"
        return chat_endpoint.replace("/api/chat", "/api/generate")

    def _post(
        self,
        url: str,
        payload: Dict[str, Any],
        *,
        timeout: Tuple[float, float],
        request_id: str,
        stream: bool = False,
    ) -> requests.Response:
        try:
            logger.debug(
                "LLM request start",
                extra={"llm_url": url, "llm_request_id": request_id},
            )
            response = self.session.post(url, json=payload, timeout=timeout, stream=stream)
            response.raise_for_status()
            return response
        except requests.Timeout as exc:
            logger.warning(
                "LLM request timeout",
                extra={"llm_url": url, "llm_request_id": request_id},
            )
            raise LLMServiceError("LLM request timed out") from exc
        except requests.RequestException as exc:
            logger.error(
                "LLM request failed",
                exc_info=True,
                extra={"llm_url": url, "llm_request_id": request_id},
            )
            raise LLMServiceError("LLM request failed") from exc

    def chat(self, payload: Dict[str, Any], *, request_id: str) -> Dict[str, Any]:
        response = self._post(
            self.chat_endpoint,
            payload,
            timeout=self.chat_timeout,
            request_id=request_id,
        )
        try:
            data = response.json()
            logger.debug(
                "LLM chat success",
                extra={"llm_request_id": request_id},
            )
            return data
        except json.JSONDecodeError as exc:
            logger.error(
                "Invalid JSON payload from LLM chat",
                exc_info=True,
                extra={"llm_request_id": request_id},
            )
            raise LLMServiceError("Invalid JSON payload from LLM chat") from exc

    def generate(self, payload: Dict[str, Any], *, request_id: str) -> str:
        response = self._post(
            self.generate_endpoint,
            payload,
            timeout=self.generate_timeout,
            request_id=request_id,
            stream=True,
        )

        content_parts: List[str] = []
        try:
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                try:
                    line = json.loads(raw_line)
                except json.JSONDecodeError:
                    logger.warning(
                        "Skipping invalid JSON line from LLM generate",
                        extra={"llm_request_id": request_id, "llm_line": raw_line},
                    )
                    continue
                content_parts.append(line.get("response", ""))
        finally:
            response.close()

        if not content_parts:
            logger.error(
                "Empty response payload from LLM generate",
                extra={"llm_request_id": request_id},
            )
            raise LLMServiceError("Empty response from LLM generate")

        text = "".join(content_parts).strip()
        logger.debug(
            "LLM generate success",
            extra={"llm_request_id": request_id},
        )
        return text


CLIENT = LLMClient(settings.LLM_ENDPOINT)

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

    attempt = 0
    last_err: Optional[str] = None
    while attempt <= max_attempts:
        try:
            messages = list(base_messages) + [{"role": "user", "content": prompt}]
            if attempt > 0 and sensitive_terms:
                # Renforcement anti-spoiler aux tentatives suivantes
                banlist = ", ".join(sensitive_terms[:5])
                messages.append({"role": "system", "content": f"Do NOT mention or allude to: {banlist}. Rephrase to avoid spoilers."})

            request_id = f"chat-{uuid4().hex}"
            data = CLIENT.chat(
                {
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
                request_id=request_id,
            )
            # Ollama /api/chat peut renvoyer {"message":{"content":...}} ou {"response":...}
            text = (data.get("message") or {}).get("content") or data.get("response") or ""
            text = _postprocess(text)

            if _has_spoiler(text, sensitive_terms):
                logger.info(
                    "LLM spoiler detected, retrying",
                    extra={"llm_request_id": request_id, "attempt": attempt + 1, "kind": kind},
                )
                attempt += 1
                continue

            logger.info(
                "LLM clue generated",
                extra={"llm_request_id": request_id, "attempt": attempt + 1, "kind": kind},
            )
            return {"text": text, "kind": kind, "attempts": attempt + 1}
        except LLMServiceError as exc:
            last_err = str(exc)
            logger.warning(
                "LLM chat attempt failed",
                exc_info=True,
                extra={"attempt": attempt + 1, "kind": kind},
            )
            attempt += 1
        except Exception as exc:
            last_err = str(exc)
            logger.exception("Unexpected error while generating clue", extra={"attempt": attempt + 1, "kind": kind})
            attempt += 1

    # Fallback minimal en cas d'échecs répétés
    logger.error(
        "LLM clue generation failed after retries",
        extra={"kind": kind, "attempts": attempt, "last_error": last_err},
    )
    return {"text": f"[stub] {kind} clue based on: {prompt[:120]}...", "kind": kind, "error": last_err or "antispam"}

def run_llm(prompt: str) -> dict:
    """
    Appelle le LLM configuré et retourne un dict { 'text': ... }.
    - Ollama /api/generate renvoie un flux JSONL → concaténation des 'response'.
    - Fallback stub si provider inconnu.
    """
    if settings.LLM_PROVIDER == "ollama":
        request_id = f"generate-{uuid4().hex}"
        try:
            text = CLIENT.generate(
                {
                    "model": settings.LLM_MODEL,
                    "prompt": prompt,
                },
                request_id=request_id,
            )
            logger.info(
                "LLM generate completed",
                extra={"llm_request_id": request_id},
            )
            return {"text": text}
        except LLMServiceError as exc:
            logger.error(
                "LLM generate failed",
                exc_info=True,
                extra={"llm_request_id": request_id},
            )
            return {
                "text": f"[stub] réponse générée à partir du prompt: {prompt[:50]}...",
                "error": str(exc),
            }

    # fallback : stub
    return {"text": f"[stub] réponse à partir du prompt: {prompt[:50]}..."}
