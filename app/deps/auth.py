# app/deps/auth.py
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config.settings import settings

bearer = HTTPBearer(auto_error=False)

def mj_required(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    """
    Dépendance FastAPI pour sécuriser les endpoints MJ via Bearer.
    Active automatiquement le bouton 'Authorize' dans Swagger UI.
    """
    if not credentials or (credentials.scheme or "").lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")
    if credentials.credentials != settings.MJ_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
    return True
