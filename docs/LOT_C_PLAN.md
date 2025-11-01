# Lot C – Suivi & Roadmap

## État actuel (PR #3 – API sessions/rounds)

- [x] Squelette REST `/session/{id}/…` : création, état brut, tirage équipes, cycle round (prepare/start/end) et soumission scores.
- [x] Flux WebSocket MJ `/ws/session/{id}` : phase courante, tick timer (mock), relai des `score_update`.
- [x] Tests FastAPI couvrant un flow round complet (prepare → start intro/confirm → end → submit) + handshake WS.
- [x] Documentation : `docs/LOT_C_PLAN.md` (présent fichier) + README backend index toujours à jour via référence.
- [ ] Front MJ : consommer les nouveaux endpoints + WS (à traiter dans PR front associée).
- [ ] Intégration timer réel + score_update alimenté (prévu PR #7).

## À faire (Lot C)

| Priorité | Tâche | Notes |
|----------|-------|-------|
| P0 | Brancher le front MJ sur `/session/{id}/state`, `/teams/draw`, `/round/{n}/start/end`, `/submit` | prévoir wrapper API coté front |
| P0 | Implémenter un buffer timer réel côté backend (RoundTimerService) et diffuser via `/ws/session/{id}` | dépend PR#7 |
| P1 | Étendre `SessionEngine` pour calculer / logguer `score_update` (actuellement mock) | alimente WS |
| P1 | Ajouter endpoints `/session/{id}/teams/draw` côté front (UI) | besoin design MJ |
| P2 | Améliorer persistance scoreboard (structurer `session.submissions`) et export final | en lien Lot D |

## Rappels

- Auth MJ requise (`Authorization: Bearer changeme-super-secret` en dev).
- Les anciennes routes (`/session/start_next`, `/session/confirm_start`, `/session/result`) restent présentes mais redirigent vers la nouvelle implémentation.
- Le flux `/ws` legacy est inchangé pour les joueurs ; `/ws/session/{id}` est dédié au dashboard MJ.
