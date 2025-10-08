@echo off
chcp 65001 >nul
color 0F
title MURDER PARTY — TEST GLOBAL BACKEND
echo.
echo ================================================
echo       TEST GLOBAL DU BACKEND MURDER PARTY
echo ================================================
echo.

call scripts\test_core.bat
if errorlevel 1 exit /b 1

call scripts\test_dynamic.bat
if errorlevel 1 exit /b 1

call scripts\test_endgame.bat
if errorlevel 1 exit /b 1

echo.
echo ================================================
echo ✅ TOUS LES TESTS ONT RÉUSSI AVEC SUCCÈS !
echo ================================================
pause
exit /b 0
