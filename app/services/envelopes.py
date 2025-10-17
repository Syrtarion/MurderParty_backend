# app/services/envelopes.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple
import json, re, heapq
from pathlib import Path
from app.services.game_state import GAME_STATE

# Le joueur ne voit que { num, id } ; le MJ peut voir le détail via /master/envelopes/summary
IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2}

def _normalize_id(val: Any) -> str:
    return str(val) if val is not None else ""

def _players_list() -> List[Dict[str, Any]]:
    return list(GAME_STATE.players.values())

def _app_root() -> Path:
    # app/services/envelopes.py -> parents[1] == app/
    return Path(__file__).resolve().parents[1]

def _seed_default_path() -> str:
    """
    Priorité:
      1) settings.STORY_SEED_PATH si défini,
      2) app/data/story_seed.json (chemin par défaut unique).
    """
    try:
        from app.config.settings import settings  # type: ignore
        if getattr(settings, "STORY_SEED_PATH", None):
            p = Path(str(settings.STORY_SEED_PATH)).expanduser()
            return str(p.resolve())
    except Exception:
        pass
    app_dir = _app_root()
    return str((app_dir / "data" / "story_seed.json").resolve())

def _load_seed_from_disk() -> Dict[str, Any]:
    """
    Lit le story_seed directement depuis le disque (sans modifier GAME_STATE).
    """
    path = _seed_default_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _get_seed_live() -> Dict[str, Any]:
    """
    Source de vérité pour la LECTURE:
      1) si GAME_STATE.state['story_seed'] existe -> on l'utilise,
      2) sinon on lit le JSON disque (seed “frais”).
    On NE sauve pas automatiquement sur disque ici.
    """
    seed_mem = GAME_STATE.state.get("story_seed")
    if isinstance(seed_mem, dict) and seed_mem:
        return seed_mem
    return _load_seed_from_disk()

def _envs_from_seed() -> List[Dict[str, Any]]:
    seed = _get_seed_live()
    envs = seed.get("envelopes") or []
    # normaliser 'id' en string pour downstream
    for e in envs:
        e["id"] = _normalize_id(e.get("id"))
    return envs

def _bucket_by_importance(envs: List[Dict[str, Any]]):
    """Retourne (high, medium, low) pour les enveloppes NON assignées."""
    high, medium, low = [], [], []
    for e in envs:
        if e.get("assigned_player_id"):
            continue
        imp = str(e.get("importance", "medium")).lower()
        idx = IMPORTANCE_ORDER.get(imp, 1)
        if idx == 0: high.append(e)
        elif idx == 1: medium.append(e)
        else: low.append(e)
    return high, medium, low

def _count_per_player(envs: List[Dict[str, Any]]) -> Dict[str, int]:
    per: Dict[str, int] = {}
    for e in envs:
        pid = e.get("assigned_player_id")
        if not pid:
            continue
        per[pid] = per.get(pid, 0) + 1
    return per

# ------------------- VUE JOUEUR (ultra minimale) -----------------------
def _sync_players_envelopes_from_seed() -> None:
    """
    Construit players[pid].envelopes (vue minimale) à partir de l’ETAT ACTUEL (mémoire):
      players[pid]["envelopes"] = [{ "num": 1, "id": "env_5" }, ...]
    On numérote par ordre d’id “numérique quand possible”.
    """
    envs = _envs_from_seed()

    # Regrouper par joueur
    by_pid: Dict[str, List[str]] = {}
    for e in envs:
        pid = e.get("assigned_player_id")
        if not pid:
            continue
        eid = _normalize_id(e.get("id"))
        by_pid.setdefault(pid, []).append(eid)

    def _env_sort_key(s: str):
        m = re.search(r'(\d+)$', s)
        return (0, int(m.group(1))) if m else (1, s)

    for pid in by_pid:
        by_pid[pid].sort(key=_env_sort_key)

    for pid, player in GAME_STATE.players.items():
        ids = by_pid.get(pid, [])
        player["envelopes"] = [{"num": i + 1, "id": eid} for i, eid in enumerate(ids)]

# ------------------- VUES / UTIL MJ -----------------------------------
def reset_envelope_assignments() -> Dict[str, Any]:
    """
    MJ utilitaire: enlève tous les assigned_player_id dans le SEED EN MEMOIRE,
    resynchronise la vue minimale côté joueurs et sauvegarde.
    (n’écrit rien sur le disque)
    """
    seed = GAME_STATE.state.get("story_seed")
    if not isinstance(seed, dict) or not seed:
        # Si pas de seed en mémoire, on en charge un depuis le disque en mémoire.
        seed = _load_seed_from_disk()
        GAME_STATE.state["story_seed"] = seed

    envs = seed.get("envelopes") or []
    for e in envs:
        if "assigned_player_id" in e:
            e["assigned_player_id"] = None
    _sync_players_envelopes_from_seed()
    GAME_STATE.save()
    return {"ok": True, "reset": len(envs)}

def summary_for_mj(include_hints: bool = False) -> Dict[str, Any]:
    """
    Résumé MJ (diagnostic) — PRÉFÈRE la mémoire (GAME_STATE). Si aucune enveloppe
    n’y est présente, retombe sur le story_seed du disque.
    Ajoute 'source' = 'memory' | 'disk' et 'seed_path' si disk.
    """
    # Déterminer la source avant de charger envs
    source = "memory"
    seed_path = None
    mem_seed = GAME_STATE.state.get("story_seed")
    mem_envs = None
    if isinstance(mem_seed, dict):
        mem_envs = mem_seed.get("envelopes") or []
    if not mem_envs:
        source = "disk"
        seed_path = _seed_default_path()

    # Charger via la même logique que le reste (et normaliser)
    envs = _envs_from_seed()
    per_player = _count_per_player(envs)
    total = len(envs)
    unassigned = [e for e in envs if not e.get("assigned_player_id")]
    payload_list = []
    for e in envs:
        d = {
            "id": _normalize_id(e.get("id")),
            "description": e.get("description"),
            "object_type": e.get("object_type"),
            "importance": e.get("importance", "medium"),
            "assigned_player_id": e.get("assigned_player_id"),
        }
        if include_hints:
            d["llm_hint"] = e.get("llm_hint")
        payload_list.append(d)
    out = {
        "total": total,
        "assigned": total - len(unassigned),
        "left": len(unassigned),
        "per_player": per_player,
        "envelopes": payload_list,
        "source": source,
    }
    if seed_path:
        out["seed_path"] = seed_path
    return out

# ------------------- DISTRIBUTION -------------------------------------
def distribute_envelopes_equitable() -> Dict[str, Any]:
    """
    Répartition équitable des enveloppes NON assignées entre joueurs.
    - Lecture: si seed mémoire présent → on l’utilise ; sinon on lit DISQUE et on met en mémoire.
    - ⚠️ FIX: équilibrage GLOBAL par “joueur le moins servi” (heap min),
      pas de restart sur chaque bucket → pas de biais vers le 1er joueur.
    - Respecte les assignations déjà existantes (idempotent).
    - Met à jour la VUE JOUEUR (num/id).
    """
    players = _players_list()
    if not players:
        return {"assigned": 0, "left": 0, "per_player": {}}

    # S’assurer d’avoir un seed en mémoire (sinon charger depuis disque)
    seed = GAME_STATE.state.get("story_seed")
    if not isinstance(seed, dict) or not seed:
        seed = _load_seed_from_disk()
        GAME_STATE.state["story_seed"] = seed

    envs = seed.get("envelopes") or []
    for e in envs:
        e["id"] = _normalize_id(e.get("id"))

    # Séparer assignées / non assignées
    already_assigned = [e for e in envs if e.get("assigned_player_id")]
    to_assign = [e for e in envs if not e.get("assigned_player_id")]

    if not to_assign:
        _sync_players_envelopes_from_seed()
        GAME_STATE.save()
        left = len([e for e in envs if not e.get("assigned_player_id")])
        return {"assigned": 0, "left": left, "per_player": _count_per_player(envs)}

    # Tri des enveloppes à assigner: importance (high→low) puis id stable (numérique si possible)
    def _env_sort_key(e: Dict[str, Any]):
        imp = str(e.get("importance", "medium")).lower()
        imp_rank = IMPORTANCE_ORDER.get(imp, 1)
        # tri id: numérique si possible
        m = re.search(r'(\d+)$', str(e.get("id")))
        id_key = (0, int(m.group(1))) if m else (1, str(e.get("id")))
        return (imp_rank, id_key)

    to_assign.sort(key=_env_sort_key)

    # Comptes initiaux (prennent en compte les déjà assignées)
    counts = _count_per_player(envs)

    # Tas min sur (count, tiebreak, player_id) — tiebreak stable pour alternance
    heap: List[Tuple[int, int, str]] = []
    for idx, p in enumerate(players):
        pid = p["player_id"]
        heapq.heappush(heap, (counts.get(pid, 0), idx, pid))

    # Assignation équitable
    assigned_now = 0
    for e in to_assign:
        cnt, tie, pid = heapq.heappop(heap)
        e["assigned_player_id"] = pid
        assigned_now += 1
        cnt += 1
        # remettre à jour dans le heap
        heapq.heappush(heap, (cnt, tie, pid))

    # Vue joueur + persist
    _sync_players_envelopes_from_seed()
    GAME_STATE.save()

    left = len([e for e in envs if not e.get("assigned_player_id")])
    return {"assigned": assigned_now, "left": left, "per_player": _count_per_player(envs)}
