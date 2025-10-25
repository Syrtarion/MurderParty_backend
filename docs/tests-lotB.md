# Lot B — Plan de tests manuels (Backend + Dashboard MJ + Room Joueur)

Prérequis :
- Backend FastAPI lancé en local sur `http://127.0.0.1:8000`.
- Token MJ par défaut `changeme-super-secret` (adapter si modifié dans `.env`).
- Front Next.js lancé (`npm run dev`) pour la vérification visuelle des écrans.

---

## 1. Préparer le contexte

### 1.1 Nettoyer les données de partie (optionnel mais recommandé en dev)
```bash
curl -X POST http://127.0.0.1:8000/admin/reset \
     -H "Authorization: Bearer changeme-super-secret"
```

### 1.2 Inscrire deux joueurs (via API ou UI)
```bash
curl -X POST http://127.0.0.1:8000/auth/register \
     -H "Content-Type: application/json" \
     -d '{"name":"Alice","password":"alice"}'

curl -X POST http://127.0.0.1:8000/auth/register \
     -H "Content-Type: application/json" \
     -d '{"name":"Eva","password":"eva"}'
```

Les joueurs reçoivent automatiquement un personnage depuis `story_seed.json`.

---

## 2. Générer le canon narratif

```bash
curl -X POST http://127.0.0.1:8000/master/generate_canon \
     -H "Authorization: Bearer changeme-super-secret" \
     -H "Content-Type: application/json" \
     -d '{}'
```

> Astuce : `/party/roles_assign` génère désormais automatiquement un canon s’il n’existe pas encore.
> L’appeler explicitement via `/master/generate_canon` reste conseillé pour vérifier le contenu avant l’assignation.

---

## 3. Vérifications côté API

### 3.1 Vérifier l’état global
```bash
curl http://127.0.0.1:8000/party/status \
     -H "Authorization: Bearer changeme-super-secret"
```
Confirmer `phase_label`, `join_locked`, `players_count`, `envelopes`.

### 3.2 Masquer les enveloppes (transition ENVELOPES_HIDDEN)
```bash
curl -X POST http://127.0.0.1:8000/party/envelopes_hidden \
     -H "Authorization: Bearer changeme-super-secret"
```

### 3.3 Assigner rôles & missions (déclenche WS `role_reveal` / `secret_mission`)
```bash
curl -X POST http://127.0.0.1:8000/party/roles_assign \
     -H "Authorization: Bearer changeme-super-secret"
```

### 3.4 Lire l’état public
```bash
curl http://127.0.0.1:8000/game/state \
     -H "Authorization: Bearer changeme-super-secret"
```
Confirmer la phase et la présence des joueurs.

### 3.5 Audit des évènements
```bash
curl http://127.0.0.1:8000/admin/events \
     -H "Authorization: Bearer changeme-super-secret"
```
Vérifier des entrées `ws_role_reveal_sent`, `ws_mission_sent` par joueur (titre mission uniquement).

---

## 4. Vérifications Dashboard MJ

1. Visiter `http://localhost:3000/mj/login`, se connecter (MJ).
2. Sur `/mj/dashboard` :
   - Les boutons « Enveloppes cachées » et « Assigner rôles & missions » doivent être cliquables et afficher un toast/log FR.
   - Le toggle « Afficher les spoilers » montre arme/lieu/mobile/coupable.
   - Les joueurs listés affichent :
     - Avatar/initiales, nom, personnage.
     - Compteur d’enveloppes.
     - Toggle « Afficher les rôles » → badge Killer/Innocent (s’ils sont assignés).

---

## 5. Vérifications Room Joueur

1. Ouvrir deux onglets `http://localhost:3000/room/<playerId>` (IDs depuis `GAME_STATE.players` ou `party/status`).
2. Avant `/party/roles_assign`, la section « Mon rôle / Ma mission » indique qu’elle attend la révélation.
3. Après l’assignation :
   - Réception WS en live → badge rôle (rouge Killer / vert Innocent) + mission (titre + description).
   - `localStorage` contient `mp_role` et `mp_mission`; un refresh conserve les informations.

---

## 6. Notes & diagnostics

- Si le tableau MJ boucle sur *« Vérification de session… »*, relancer le backend et vérifier le cookie MJ (`/mj/login`).
- Les `ws_role_reveal_sent` et `ws_mission_sent` sont stockés dans `app/data/events.json` pour audit post-partie.
- En cas de test supplémentaire : `/master/envelopes/summary` (récap complet), `/party/status` (phase + enveloppes).
