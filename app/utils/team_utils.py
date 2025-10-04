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

    - Si team_count est fourni: crée ce nombre d'équipes (taille ~équilibrée, inégale OK).
    - Sinon si team_size est fourni: calcule team_count = ceil(n / team_size).
    - Sinon: par défaut crée 2 équipes.
    - seed permet de rejouer le tirage (debug / fairness).
    """
    if not players:
        return {}

    rng = random.Random(seed) if seed is not None else random
    pool = players[:]
    rng.shuffle(pool)

    if team_count is None and team_size is None:
        team_count = 2
    if team_count is None and team_size is not None:
        team_count = max(1, math.ceil(len(pool) / max(1, team_size)))
    team_count = max(1, int(team_count))

    teams = {f"{team_prefix}{i+1}": [] for i in range(team_count)}

    # distribution en round-robin après shuffle (équipes inégales possibles)
    i = 0
    keys = list(teams.keys())
    for p in pool:
        teams[keys[i % team_count]].append(p)
        i += 1

    return teams
