"""
Service: character_service.py
Rôle:
- Gérer l'attribution des personnages et enveloppes aux joueurs.
- Deux modes:
  1) Mode "seed": lit/écrit directement dans GAME_STATE.state["story_seed"].
  2) Mode "legacy": persiste via fichiers `characters.json` et `characters_assigned.json`.

Intégrations:
- GAME_STATE: accès au story_seed en mémoire + save globale.
- io_utils: lecture/écriture JSON legacy.
- settings.DATA_DIR: répertoires des fichiers.

Notes de conception:
- Verrou RLock pour sécuriser les accès concurrents (WS + endpoints).
- `list_available()` retourne les rôles non assignés; `assign_character()` consomme un rôle.
- `assign_envelopes()` ne fonctionne qu'en mode seed (retourne [] en legacy).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Dict, Any, Optional, List

from app.config.settings import settings
from .io_utils import read_json, write_json
from app.services.game_state import GAME_STATE

DATA_DIR = Path(settings.DATA_DIR)
CHAR_PATH = DATA_DIR / "characters.json"            # mode legacy (sans story_seed)
ASSIGN_PATH = DATA_DIR / "characters_assigned.json" # mode legacy (mapping player_id -> character_id)

@dataclass
class CharacterService:
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    # --- MODE LEGACY (fichiers) ---
    characters: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # id -> character
    assigned: Dict[str, str] = field(default_factory=dict)               # player_id -> character_id

    def _seed(self) -> Optional[Dict[str, Any]]:
        """Retourne le story_seed courant si présent, sinon None (mode legacy)."""
        seed = GAME_STATE.state.get("story_seed")
        return seed if isinstance(seed, dict) else None

    def _use_seed(self) -> bool:
        """True si l'app fonctionne en mode story_seed (prioritaire), False si legacy fichiers."""
        return self._seed() is not None

    # -------------------------
    # Chargement / Sauvegarde
    # -------------------------
    def load(self) -> None:
        """Charge les données en mode legacy. En mode seed, rien à faire (lecture via GAME_STATE)."""
        with self._lock:
            if self._use_seed():
                # Story seed en mémoire: pas de chargement fichier requis
                return
            raw = read_json(CHAR_PATH) or {"characters": []}
            self.characters = {c["id"]: c for c in raw.get("characters", [])}
            self.assigned = read_json(ASSIGN_PATH) or {}

    def save(self) -> None:
        """Persiste: en mode seed → GAME_STATE.save(); en legacy → écrit le mapping assigned."""
        with self._lock:
            if self._use_seed():
                GAME_STATE.save()
            else:
                write_json(ASSIGN_PATH, self.assigned)

    # -------------------------
    # Characters (rôles)
    # -------------------------
    def list_available(self) -> Dict[str, Dict[str, Any]]:
        """Retourne les personnages disponibles (non assignés) selon le mode actif."""
        with self._lock:
            if self._use_seed():
                seed = self._seed() or {}
                chars: List[Dict[str, Any]] = seed.get("characters") or []
                free = {}
                for ch in chars:
                    if not isinstance(ch, dict):
                        continue
                    cid = str(ch.get("id") or "")
                    if cid and not ch.get("assigned_player_id"):
                        free[cid] = ch
                return free
            else:
                used = set(self.assigned.values())
                return {cid: c for cid, c in self.characters.items() if cid not in used}

    def get_assigned(self, player_id: str) -> Optional[Dict[str, Any]]:
        """Retourne le personnage déjà assigné à player_id, ou None s'il n'y en a pas."""
        with self._lock:
            if self._use_seed():
                seed = self._seed() or {}
                chars: List[Dict[str, Any]] = seed.get("characters") or []
                for ch in chars:
                    if isinstance(ch, dict) and ch.get("assigned_player_id") == player_id:
                        return ch
                return None
            else:
                cid = self.assigned.get(player_id)
                if not cid:
                    return None
                return self.characters.get(cid)

    def assign_character(self, player_id: str) -> Optional[Dict[str, Any]]:
        """
        Attribue un rôle au joueur si disponible.
        - Mode seed: marque `assigned_player_id` dans story_seed.characters[] puis sauvegarde.
        - Mode legacy: met à jour `self.assigned` puis sauvegarde le mapping.
        Retourne le dict du personnage, ou None si plus aucun rôle libre.
        """
        with self._lock:
            # Si déjà attribué, renvoyer l'existant (idempotent)
            current = self.get_assigned(player_id)
            if current:
                return current

            if self._use_seed():
                free = self.list_available()
                if not free:
                    return None
                # Choix simple: premier disponible (déterministe sur l'ordre de fichier)
                cid, ch = next(iter(free.items()))
                ch["assigned_player_id"] = player_id
                self.save()
                return ch
            else:
                free = self.list_available()
                if not free:
                    return None
                cid, ch = next(iter(free.items()))
                self.assigned[player_id] = cid
                self.save()
                return ch

    # -------------------------
    # Enveloppes
    # -------------------------
    def assign_envelopes(self, player_id: str, count: int = 1) -> List[Dict[str, Any]]:
        """
        Attribue `count` enveloppes non assignées depuis story_seed.envelopes (mode seed).
        - Met à jour `assigned_player_id` sur chaque enveloppe.
        - Legacy: renvoie [] (non pris en charge).
        """
        with self._lock:
            if not self._use_seed():
                return []
            seed = self._seed() or {}
            envs: List[Dict[str, Any]] = seed.get("envelopes") or []
            given: List[Dict[str, Any]] = []
            for env in envs:
                if not isinstance(env, dict):
                    continue
                if env.get("assigned_player_id"):
                    continue
                env["assigned_player_id"] = player_id
                given.append(env)
                if len(given) >= count:
                    break
            if given:
                self.save()
            return given


# Instance globale (chargée au démarrage)
CHARACTERS = CharacterService()
CHARACTERS.load()
