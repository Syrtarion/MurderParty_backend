@echo off
setlocal enabledelayedexpansion

echo [*] Test automatisé - Déroulement complet de 2 rounds
echo --------------------------------------------

set BASE_URL=http://localhost:8000
set AUTH_HEADER=Authorization: Bearer changeme-super-secret
set JSON_HEADER=Content-Type: application/json

echo [1] Statut initial de la session
curl -s -X GET %BASE_URL%/session/status -H "%AUTH_HEADER%" | jq .

echo.
echo [2] >>> Lancement du premier round
curl -s -X POST %BASE_URL%/session/start_next -H "%AUTH_HEADER%" | jq .

echo.
echo [3] >>> Confirmation du démarrage du mini-jeu
curl -s -X POST %BASE_URL%/session/confirm_start -H "%AUTH_HEADER%" | jq .

echo.
echo [4] >>> Simulation : résultats du round 1 (2 gagnants)
curl -s -X POST %BASE_URL%/session/result ^
 -H "%AUTH_HEADER%" ^
 -H "%JSON_HEADER%" ^
 -d "{\"winners\": [\"player_1\", \"player_2\"], \"meta\": {\"scores\": {\"player_1\": 12, \"player_2\": 9}}}" | jq .

echo.
echo [5] >>> Lancement du second round
curl -s -X POST %BASE_URL%/session/start_next -H "%AUTH_HEADER%" | jq .

echo.
echo [6] >>> Confirmation du démarrage du round 2
curl -s -X POST %BASE_URL%/session/confirm_start -H "%AUTH_HEADER%" | jq .

echo.
echo [7] >>> Fin du round 2 (1 gagnant)
curl -s -X POST %BASE_URL%/session/result ^
 -H "%AUTH_HEADER%" ^
 -H "%JSON_HEADER%" ^
 -d "{\"winners\": [\"player_3\"], \"meta\": {\"scores\": {\"player_3\": 15}}}" | jq .

echo.
echo [8] >>> Vérification de l'état final
curl -s -X GET %BASE_URL%/session/status -H "%AUTH_HEADER%" | jq .

echo --------------------------------------------
echo [*] Test terminé
pause
