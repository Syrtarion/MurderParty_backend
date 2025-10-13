"""
Utilitaires IO JSON (rapides) basés sur orjson.
- read_json(Path)  → Any | None (None si fichier manquant)
- write_json(Path, data) → écrit en binaire (création des dossiers si besoin)

Attention:
- orjson renvoie/attend des bytes; on lit/écrit en mode binaire.
- write_json ne met pas d'indentation (performance/praticité).
"""
import orjson as json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    """Lit un fichier JSON (ou None s'il n'existe pas)."""
    if not path.exists():
        return None
    with path.open("rb") as f:
        return json.loads(f.read())


def write_json(path: Path, data: Any) -> None:
    """Écrit un fichier JSON de manière sûre (dossier parent créé si absent)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(json.dumps(data))
