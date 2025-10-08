# ====================================================
# Test automatisé - Génération canon + intro narrative
# ====================================================
Clear-Host
Write-Host "`n=== TEST DU FLUX CANON + INTRO ===`n" -ForegroundColor Cyan

$baseUrl = "http://localhost:8000"
$authHeader = @{ "Authorization" = "Bearer changeme-super-secret" }
$contentType = @{ "Content-Type" = "application/json" }

# ----------------------------------------------------
# Étape 1 : Génération du canon
# ----------------------------------------------------
Write-Host "[1] Génération du canon narratif..." -ForegroundColor Yellow
$canonBody = '{"style": "dramatique, gothique"}'
$canonResp = Invoke-RestMethod -Uri "$baseUrl/master/generate_canon" -Headers $authHeader -Body $canonBody -Method POST -ContentType "application/json"

if ($canonResp.ok -eq $true) {
    Write-Host "Canon généré avec succès ✅" -ForegroundColor Green
    Write-Host "Coupable tiré au hasard : $($canonResp.canon.culprit_name)"
    Write-Host "Arme : $($canonResp.canon.weapon) / Lieu : $($canonResp.canon.location) / Mobile : $($canonResp.canon.motive)`n"
} else {
    Write-Host "Erreur lors de la génération du canon ❌" -ForegroundColor Red
    $canonResp | ConvertTo-Json -Depth 5
    exit
}

# Pause courte pour lisibilité
Start-Sleep -Seconds 1

# ----------------------------------------------------
# Étape 2 : Génération de l'intro
# ----------------------------------------------------
Write-Host "[2] Génération de l'introduction immersive..." -ForegroundColor Yellow
$introResp = Invoke-RestMethod -Uri "$baseUrl/master/intro" -Headers $authHeader -Method POST

if ($introResp.ok -eq $true) {
    Write-Host "Intro générée avec succès ✅" -ForegroundColor Green
    Write-Host "`n--- INTRO ---`n" -ForegroundColor DarkCyan
    Write-Host $introResp.intro_text -ForegroundColor White
    Write-Host "`n---------------`n"
} else {
    Write-Host "Erreur lors de la génération de l'intro ❌" -ForegroundColor Red
    $introResp | ConvertTo-Json -Depth 5
    exit
}

# Pause courte
Start-Sleep -Seconds 1

# ----------------------------------------------------
# Étape 3 : Vérification du canon_narratif.json
# ----------------------------------------------------
Write-Host "[3] Vérification du fichier canon_narratif.json..." -ForegroundColor Yellow
$canonPath = "H:\murderparty_backend\app\data\canon_narratif.json"

if (Test-Path $canonPath) {
    $canonData = Get-Content $canonPath -Raw | ConvertFrom-Json
    $timeline = $canonData.timeline
    $lastEvent = $timeline[-1]
    Write-Host "Dernier événement ajouté : $($lastEvent.event)" -ForegroundColor Green
    Write-Host "Texte : $($lastEvent.text.Substring(0, [Math]::Min(120, $lastEvent.text.Length)))..." -ForegroundColor White
} else {
    Write-Host "Fichier canon_narratif.json introuvable ❌" -ForegroundColor Red
}

Write-Host "`n--------------------------------------"
Write-Host "[*] Test terminé ✅" -ForegroundColor Cyan
Write-Host "Cliquez sur Entrée pour fermer..." -ForegroundColor Gray
Read-Host
