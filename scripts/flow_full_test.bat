@echo off
setlocal

REM === CONFIG ===
set BASE=http://localhost:8000
set TOKEN=changeme-super-secret

echo [1] Reset game
curl -s -X POST %BASE%/admin/reset_game -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json"
echo.

echo [2] Create players
curl -s -X POST %BASE%/players/join -H "Content-Type: application/json" -d "{\"display_name\":\"Alice\"}"
echo.
curl -s -X POST %BASE%/players/join -H "Content-Type: application/json" -d "{\"display_name\":\"Bob\"}"
echo.
curl -s -X POST %BASE%/players/join -H "Content-Type: application/json" -d "{\"display_name\":\"Charlie\"}"
echo.

echo [3] Generate canon (weapon/location/motive + random culprit)
curl -s -X POST %BASE%/master/generate_canon -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{}"
echo.

echo [4] Reveal culprit + assign missions
curl -s -X POST %BASE%/master/reveal_culprit -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{}"
echo.

echo [5] Show final game state (players + missions + scores)
curl -s -X GET %BASE%/game/state
echo.

endlocal
