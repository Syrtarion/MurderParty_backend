"""
Utils: team_utils.py
Rôle:
- Former des équipes aléatoires à partir d'une liste de player_ids.

Comportement:
- Si `team_count` est fourni → crée exactement ce nombre d'équipes (répartition en round-robin).
- Sinon si `team_size` est fourni → calcule `team_count = ceil(n / team_size)`.
- Sinon → défaut à 2 équipes.
- `seed` permet de rejouer le tirage (déterministe pour tests / fairness).

Notes d'implémentation:
- On shuffle la liste puis on distribue en round-robin (équipes quasi équilibrées).
- Les tailles peuvent être inégales si la division n'est pas exacte (accepté).
"""
import random, math
from typing import List, Dict, Optional


def random_teams(
    players: List[str],
    team_count: Optional[int] = None,
    team_size: Optional[int] = None,
    seed: Optional[int] = None,
    team_prefix: str = "T",
) -> Dict[str, List[str]]:
    """
    Répartit une liste de joueurs en équipes aléatoires.

    Args:
        players: liste des player_ids à répartir.
        team_count: nombre d'équipes souhaité (prioritaire sur team_size).
        team_size: taille visée par équipe (utilisée si team_count est None).
        seed: graine RNG pour un tirage reproductible.
        team_prefix: préfixe des noms d'équipes (ex: "T1", "T2", ...).

    Returns:
        Dict[str, List[str]]: mapping "T1"→[pids], "T2"→[pids], etc.

    Stratégie:
    1) Copie + mélange (`shuffle`) de la liste des joueurs.
    2) Détermination de `team_count` (priorité au paramètre explicite).
    3) Distribution en round-robin pour limiter les écarts de taille.
    """
    if not players:
        # Cas bord: aucun joueur → pas d'équipes
        return {}

    # RNG optionnelle (déterministe si seed fourni)
    rng = random.Random(seed) if seed is not None else random
    pool = players[:]
    rng.shuffle(pool)  # mélange in-place sur la copie

    # Détermination du nombre d'équipes
    if team_count is None and team_size is None:
        team_count = 2  # défaut: deux équipes
    if team_count is None and team_size is not None:
        # ceil(n / size) pour atteindre ~la taille cible
        team_count = max(1, math.ceil(len(pool) / max(1, team_size)))
    team_count = max(1, int(team_count))  # garde-fou

    # Prépare la structure des équipes: T1, T2, ..., Tn
    teams = {f"{team_prefix}{i+1}": [] for i in range(team_count)}

    # Distribution en round-robin après shuffle
    i = 0
    keys = list(teams.keys())
    for p in pool:
        teams[keys[i % team_count]].append(p)
        i += 1

    return teams
