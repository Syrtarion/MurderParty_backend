"""
Dépendance d'authentification MJ (Maître du Jeu)
================================================

Rôle
----
- Fournir une *dependency* FastAPI `mj_required` pour protéger les endpoints réservés au MJ.
- Repose sur un schéma Bearer (header `Authorization: Bearer <MJ_TOKEN>`).

Intégrations
------------
- `settings.MJ_TOKEN` : jeton secret attendu côté serveur.
- À utiliser dans les routes : `dependencies=[Depends(mj_required)]` ou
  paramètre de fonction `mj_ok: bool = Depends(mj_required)`.

Comportement & codes retour
---------------------------
- 401 si le header Authorization est manquant ou non-Bearer.
- 403 si le token Bearer ne correspond pas à `MJ_TOKEN`.
- Retourne `True` en cas de succès (inutile en soi, mais pratique pour typer/valider).

Notes
-----
- `HTTPBearer(auto_error=False)` évite que FastAPI intercepte l'erreur avant nous ; cela
  nous permet d'unifier la réponse (401/403) à la main.
- Cette dépendance active automatiquement le bouton "Authorize" dans la Swagger UI (OpenAPI).
"""

# app/deps/auth.py
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config.settings import settings

# Schéma d'authentification Bearer (ne lève pas d'erreur auto)
bearer = HTTPBearer(auto_error=False)

def mj_required(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    """
    Exige une authentification Bearer MJ pour l'accès à une route.

    Paramètres
    ----------
    credentials : HTTPAuthorizationCredentials
        Injecté par FastAPI via le schéma `HTTPBearer`.
        Contient `scheme` (ex: "Bearer") et `credentials` (le token).

    Exceptions
    ----------
    HTTPException 401 :
        - Absence du header Authorization.
        - Schéma différent de Bearer.
    HTTPException 403 :
        - Token incorrect par rapport à `settings.MJ_TOKEN`.

    Retour
    ------
    bool
        True si l'authentification est valide (aucune autre utilisation requise).
    """
    # Vérifie la présence d'un header Authorization de type Bearer
    if not credentials or (credentials.scheme or "").lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")

    # Compare la valeur du token avec celle configurée côté serveur
    if credentials.credentials != settings.MJ_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    # Laisse la route continuer ; la valeur n'est pas utilisée par la suite
    return True
