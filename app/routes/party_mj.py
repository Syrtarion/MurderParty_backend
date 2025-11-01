"""
Module routes/party_mj.py
Rôle:
- Contrôles "macro" du MJ sur le déroulé de la soirée (phases).
- Démarre la partie, ouvre/ferme l'inscription, chaîne enveloppes → personnages → rôles/missions → session.

Intégrations:
- MJ (services.mj_engine): moteur d'état côté MJ (phases, transitions) [optionnel].
- GAME_STATE: gestion de phase/join_locked, log/persist, accès players & story_seed.
- WS: diffusions d'événements "phase_change", "join_unlocked", envois ciblés joueurs.

Endpoints principaux:
- POST /party/start                : phase WAITING_PLAYERS, ouvre inscriptions.
- POST /party/envelopes_hidden    : phase ENVELOPES_HIDDEN (les enveloppes sont cachées IRL, prêtes).
- POST /party/roles_assign        : choisit le canon (tueur/arme/lieu/motif) + assigne missions secondaires (stub).
- POST /party/session_start       : passe la partie en SESSION_ACTIVE.
- GET  /party/status              : état synthétique côté MJ.

Compat rétro:
- POST /party/players_ready  → équivalent logique au verrouillage/distribution (utilise /master/lock_join côté logique).
- POST /party/envelopes_done → alias vers /party/roles_assign (fin enveloppes ⇒ rôles/missions).

Notes:
- La distribution équitable des enveloppes est déclenchée par /master/lock_join (router séparé).
- Ici, on gère l’étape "enveloppes cachées" (signal MJ) puis la révélation des rôles/missions.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any

from app.deps.auth import mj_required
from app.services.game_state import GAME_STATE
from app.services.ws_manager import WS

# (Optionnel) Moteur MJ si tu l'utilises encore
try:
    from app.services.mj_engine import MJ  # type: ignore
    _HAS_MJ = True
except Exception:
    _HAS_MJ = False

router = APIRouter(prefix="/party", tags=["party"], dependencies=[Depends(mj_required)])


@router.post("/start")
async def party_start():
    """
    Démarre la partie :
      - phase_label = WAITING_PLAYERS
      - join_locked = False (ouverture des inscriptions)
      - broadcast d’un événement 'phase_change' + 'join_unlocked'
    """
    try:
        # phase moteur (optionnel)
        if _HAS_MJ:
            from app.services.mj_engine import WAITING_PLAYERS  # type: ignore
            MJ.set_phase(WAITING_PLAYERS)
            phase = WAITING_PLAYERS
        else:
            phase = "WAITING_PLAYERS"

        # ouverture des inscriptions côté état global
        GAME_STATE.state["phase_label"] = phase
        GAME_STATE.state["join_locked"] = False
        GAME_STATE.log_event("phase_change", {"phase": phase})
        GAME_STATE.save()

        # diffusion WebSocket
        await WS.broadcast(
            {
                "type": "event",
                "kind": "phase_change",
                "phase": phase,
                "text": "La partie démarre. Les invités peuvent arriver.",
            }
        )
        await WS.broadcast_type("event", {"kind": "join_unlocked"})

        return {"ok": True, "phase": phase, "join_locked": False}
    except Exception as e:
        raise HTTPException(500, f"Cannot start party: {e}")


@router.post("/envelopes_hidden")
async def envelopes_hidden():
    """
    Confirme que les enveloppes ont été cachées/prêtes IRL.
    Passe à la phase ENVELOPES_HIDDEN (le MJ peut ensuite lancer /party/roles_assign).
    """
    try:
        phase = "ENVELOPES_HIDDEN"
        GAME_STATE.state["phase_label"] = phase
        GAME_STATE.log_event("phase_change", {"phase": phase})
        GAME_STATE.save()
        await WS.broadcast_type("event", {"kind": "phase_change", "phase": phase})
        return {"ok": True, "phase": phase}
    except Exception as e:
        raise HTTPException(500, f"Cannot set envelopes_hidden: {e}")


@router.post("/roles_assign")
async def roles_assign():
    """
    Valide le canon (coupable/arme/lieu/motif) + attribue les missions secondaires à chaque joueur.
    ⚠️ Ceci est un STUB à remplacer par le moteur LLM :
       - choix du tueur cohérent avec le seed et les indices,
       - missions adaptées à chaque personnage.
    Diffuse:
      - WS ciblé 'role_reveal' à chaque joueur
      - WS ciblé 'mission' pour sa mission secondaire
      - WS broadcast 'roles_assigned' + 'phase_change' → ROLES_ASSIGNED
    """
    try:
        players = GAME_STATE.players
        if not players:
            raise HTTPException(400, "No players")

        pids = list(players.keys())
        # --- STUB LLM: choisir un tueur + canon
        killer_id = pids[0]
        canon: Dict[str, Any] = {
            "killer_player_id": killer_id,
            "weapon": "Couteau",
            "place": "Salon",
            "motive": "Jalousie",
        }
        GAME_STATE.state["canon"] = canon

        # missions secondaires (placeholder)
        for pid, p in players.items():
            # révélation personnelle (tueur / non-tueur)
            await WS.send_to_player(pid, {"type": "role_reveal", "payload": {"is_killer": pid == killer_id}})

            mission = {
                "title": "Observer discrètement",
                "details": "Collecte 2 indices sans te faire remarquer.",
            }
            missions = p.get("missions", [])
            missions.append(mission)
            p["missions"] = missions

            await WS.send_to_player(pid, {"type": "mission", "payload": mission})

        phase = "ROLES_ASSIGNED"
        GAME_STATE.state["phase_label"] = phase
        GAME_STATE.log_event("roles_assigned", canon)
        GAME_STATE.save()

        await WS.broadcast_type("event", {"kind": "roles_assigned"})
        await WS.broadcast_type("event", {"kind": "phase_change", "phase": phase})

        return {"ok": True, "phase": phase, "canon": GAME_STATE.state.get("canon")}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"roles_assign failed: {e}")


async def _transition_session_active(*, enforce_locked: bool, use_llm_intro: bool) -> dict:
    """
    Mutualise la logique de lancement de session.
    - enforce_locked : exige que join_locked soit vrai avant de lancer.
    - use_llm_intro : drapeau conservé pour le pipeline d'intro automatisé (future PR).
    """
    if enforce_locked and not GAME_STATE.state.get("join_locked", False):
        raise HTTPException(status_code=409, detail="Verrouillez les inscriptions avant de démarrer la session.")

    phase = "SESSION_ACTIVE"
    GAME_STATE.state["phase_label"] = phase
    GAME_STATE.state["started"] = True
    GAME_STATE.log_event(
        "session_launch",
        {"phase": phase, "enforce_locked": enforce_locked, "use_llm_intro": use_llm_intro},
    )
    GAME_STATE.log_event("phase_change", {"phase": phase})
    GAME_STATE.save()

    await WS.broadcast_type("event", {"kind": "phase_change", "phase": phase})

    payload = {"ok": True, "phase": phase}
    if enforce_locked:
        payload["use_llm_intro"] = use_llm_intro
    return payload


@router.post("/session_start")
async def session_start():
    """
    Passe la partie en SESSION_ACTIVE (début du jeu libre).
    Conservé pour compatibilité, sans imposer le verrouillage préalable.
    """
    try:
        return await _transition_session_active(enforce_locked=False, use_llm_intro=True)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Cannot start session: {e}")


@router.post("/launch")
async def party_launch(
    use_llm_intro: bool = Query(
        default=True,
        description="Préparer automatiquement l'introduction via LLM avant de lancer la session.",
    ),
):
    """
    Endpoint principal pour le bouton "Démarrer la partie" (front MJ).
    - Exige que les inscriptions soient verrouillées.
    - Passe la partie en SESSION_ACTIVE.
    """
    try:
        return await _transition_session_active(enforce_locked=True, use_llm_intro=use_llm_intro)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Cannot launch party: {e}")


@router.get("/status")
async def party_status():
    """
    Snapshot synthétique de l'état côté MJ (utile au dashboard):
    - phase_label
    - join_locked
    - players_count
    - (optionnel) status moteur MJ si présent
    """
    try:
        state = {
            "phase_label": GAME_STATE.state.get("phase_label"),
            "join_locked": GAME_STATE.state.get("join_locked"),
            "players_count": len(GAME_STATE.players),
        }
        if _HAS_MJ:
            try:
                state["mj"] = MJ.status()  # type: ignore
            except Exception:
                state["mj"] = {"ok": False}
        return {"ok": True, **state}
    except Exception as e:
        raise HTTPException(500, f"status failed: {e}")


# ----------------------------
# Compatibilité rétro (alias)
# ----------------------------

@router.post("/players_ready")
async def party_players_ready():
    """
    ✅ Alias historique
    Anciennement: fin d'arrivée des joueurs → distribution des enveloppes & verrouillage.
    Nouveau flow officiel:
      - Utilise /master/lock_join (router master) pour verrouiller et distribuer équitablement.
    Ici on renvoie un message d’orientation pour ne pas casser les clients existants.
    """
    return {
        "ok": True,
        "note": "Use /master/lock_join to lock registrations and distribute envelopes.",
        "redirect": "/master/lock_join",
    }


@router.post("/envelopes_done")
async def party_envelopes_done():
    """
    ✅ Alias historique
    Anciennement: fin enveloppes ⇒ attribuer personnages.
    Nouveau flow officiel:
      - Les personnages sont attribués à l’inscription,
      - Ici on passe désormais à l’étape 'rôles & missions'.
    On appelle donc l’endpoint /party/roles_assign.
    """
    # on appelle directement la logique de roles_assign pour ne pas dupliquer
    return await roles_assign()
