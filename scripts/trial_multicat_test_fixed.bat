@echo off
setlocal

REM ====== CONFIG ======
set BASE=http://localhost:8000
set TOKEN=changeme-super-secret

REM ====== PLAYER IDS (remplacer si besoin) ======
set P1=de7f717a-795c-420b-9fd1-c806cfe9e203
set P2=37330681-2d26-4650-adc0-01752ee4b9c9
set P3=e8a4aa6f-375d-48d2-a74e-37450e6ba745

echo Using players:
echo P1=%P1%
echo P2=%P2%
echo P3=%P3%

echo.
echo [1] Each player votes

REM --- Votes P1 (tout correct) ---
curl -s -X POST %BASE%/trial/vote -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
 -d "{\"voter_id\":\"%P1%\",\"category\":\"culprit\",\"value\":\"Camille D.\"}"
echo.
curl -s -X POST %BASE%/trial/vote -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
 -d "{\"voter_id\":\"%P1%\",\"category\":\"weapon\",\"value\":\"Chandelier\"}"
echo.
curl -s -X POST %BASE%/trial/vote -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
 -d "{\"voter_id\":\"%P1%\",\"category\":\"location\",\"value\":\"Bibliothèque\"}"
echo.
curl -s -X POST %BASE%/trial/vote -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
 -d "{\"voter_id\":\"%P1%\",\"category\":\"motive\",\"value\":\"Dette ancienne\"}"
echo.

REM --- Votes P2 (2 correct, 2 faux) ---
curl -s -X POST %BASE%/trial/vote -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
 -d "{\"voter_id\":\"%P2%\",\"category\":\"culprit\",\"value\":\"Alexandre P.\"}"
echo.
curl -s -X POST %BASE%/trial/vote -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
 -d "{\"voter_id\":\"%P2%\",\"category\":\"weapon\",\"value\":\"Chandelier\"}"
echo.
curl -s -X POST %BASE%/trial/vote -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
 -d "{\"voter_id\":\"%P2%\",\"category\":\"location\",\"value\":\"Salon\"}"
echo.
curl -s -X POST %BASE%/trial/vote -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
 -d "{\"voter_id\":\"%P2%\",\"category\":\"motive\",\"value\":\"Dette ancienne\"}"
echo.

REM --- Votes P3 (1 correct seulement) ---
curl -s -X POST %BASE%/trial/vote -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
 -d "{\"voter_id\":\"%P3%\",\"category\":\"culprit\",\"value\":\"Camille D.\"}"
echo.
curl -s -X POST %BASE%/trial/vote -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
 -d "{\"voter_id\":\"%P3%\",\"category\":\"weapon\",\"value\":\"Couteau\"}"
echo.
curl -s -X POST %BASE%/trial/vote -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
 -d "{\"voter_id\":\"%P3%\",\"category\":\"location\",\"value\":\"Salon\"}"
echo.
curl -s -X POST %BASE%/trial/vote -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" ^
 -d "{\"voter_id\":\"%P3%\",\"category\":\"motive\",\"value\":\"Jalousie\"}"
echo.

echo.
echo [2] Show tally
curl -s -X GET %BASE%/trial/tally -H "Authorization: Bearer %TOKEN%"
echo.

echo.
echo [3] Final verdict (collective + individual scores)
curl -s -X POST %BASE%/trial/verdict -H "Authorization: Bearer %TOKEN%"
echo.

echo.
echo [4] Leaderboard (players sorted by score_total)
curl -s -X GET %BASE%/game/leaderboard
echo.

endlocal
