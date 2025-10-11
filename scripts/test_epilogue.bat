@echo off
echo =============================================
echo [TEST EPILOGUE] Génération de la fin d'enquête
echo =============================================

curl -s -X POST http://localhost:8000/master/epilogue ^
 -H "Authorization: Bearer changeme-super-secret" ^
 -H "Content-Type: application/json" ^
 -d "{\"style\":\"tragique\"}"

echo.
echo ---------------------------------------------
echo ✅ Test terminé
pause
