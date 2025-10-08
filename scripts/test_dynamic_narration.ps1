# ==========================================
# TEST DU FLUX NARRATIF DYNAMIQUE COMPLET
# ==========================================

$base = "http://localhost:8000"
$auth = "changeme-super-secret"

Write-Host ""
Write-Host "=== TEST DU FLUX NARRATIF DYNAMIQUE ==="
Write-Host ""

# 1️⃣ Fin de mini-jeu (SOLO)
Write-Host "[1] Fin de mini-jeu (SOLO)"

$mg_payload = @{
    mode      = "solo"
    winners   = @("2b9bad1c-8239-4c12-8562-25c2f39045e5")
    losers    = @("0a563eda-e25f-4b67-9ea4-ebc190a303c1", "b6ea0b3c-8205-4cdf-bcac-96b6b1856b02")
    mini_game = "enigme_clef"
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "$base/master/narrate_mg_end" -Method POST -Headers @{
    "Authorization" = "Bearer $auth"
    "Content-Type"  = "application/json"
} -Body $mg_payload | ConvertTo-Json -Depth 5 | Write-Host

Start-Sleep -Seconds 2

# 2️⃣ Enveloppe scannée
Write-Host ""
Write-Host "[2] Enveloppe scannée (indice global)"

$env_payload = @{
    player_id   = "2b9bad1c-8239-4c12-8562-25c2f39045e5"
    envelope_id = "E7"
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "$base/master/narrate_envelope" -Method POST -Headers @{
    "Authorization" = "Bearer $auth"
    "Content-Type"  = "application/json"
} -Body $env_payload | ConvertTo-Json -Depth 5 | Write-Host

Start-Sleep -Seconds 2

# 3️⃣ Événement narratif automatique
Write-Host ""
Write-Host "[3] Événement narratif automatique"

$auto_payload = @{
    theme   = "ambiance"
    context = @{
        situation = "Le manoir s'assombrit, un orage gronde au loin."
    }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri "$base/master/narrate_auto" -Method POST -Headers @{
    "Authorization" = "Bearer $auth"
    "Content-Type"  = "application/json"
} -Body $auto_payload | ConvertTo-Json -Depth 5 | Write-Host

Write-Host ""
Write-Host "--------------------------------------"
Write-Host "Test terminé. Vérifie app/data/canon_narratif.json"
Write-Host "--------------------------------------"
pause
