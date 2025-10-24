# Audit backend FastAPI

## Resume executif
- Risques critiques sur les appels LLM: absence de retries/backoff, erreurs silencieuses renvoyees comme si tout allait bien, aucun log pour diagnostiquer les pannes (cf. `app/services/llm_engine.py`, `app/routes/master*.py`, `app/services/narrative_*`).
- Aucun test automatise: le dossier `tests/` est vide, `pytest` n'est pas installe et la commande `pytest -q` echoue (voir section "Verification locale"), rendant la CI inefficace.
- Journaux non structurels: usage massif de `print()` sans contexte ni correlation id; impossible de tracer une requete ou un appel LLM.
- Secrets et donnees runtime commits: `.env` (token MJ, mots de passe) et `app/data/*.json` (hash de mots de passe joueurs, sessions MJ) sont presents dans le repo malgre le `.gitignore`.
- CI GitHub presente mais rouge par construction: `requirements.txt` n'installe pas `pytest`, donc le job `ci-backend.yml` echoue a chaque execution.

## Verification locale
- `pytest -q` (depuis `h:\murderparty\murderparty_backend`) : **KO** (`pytest` introuvable), ce qui confirme qu'aucun environnement de test n'est operationnel.

## Constat detaille

### Robustesse des appels LLM (Critique)
- `run_llm` (app/services/llm_engine.py:136) effectue un `requests.post` sans retries ni backoff et laisse remonter les exceptions; toutes les routes qui l'utilisent (`app/routes/master_canon.py`, `master_epilogue.py`, `services/narrative_dynamic.py`, `session_engine.py`, etc.) n'ont qu'un `try/except` global qui renvoie une 500 sans journaliser.
- `generate_indice` retourne un stub `[stub] ...` meme en cas d'erreur (app/services/llm_engine.py:117) et les appelants ne verifient jamais `error`; le front recoit donc un faux succes silencieux.
- Aucune temporisation progressive ni jitter. Les timeouts sont fixes (45s et 60s) et un LLM lent bloque la route entiere; pas de protection contre la saturation.
- `run_llm` ne consomme pas le flux JSONL Ollama de maniere robuste: un JSON invalide coupe toutes les lignes sans trace.
- `requests.Session` global (`SESSION`) n'est pas reapplique a `run_llm`, ce qui casse la reutilisation de connexions et la configuration eventuelle de proxies/custom headers.

### Tests et integration LLM (Critique)
- Aucun test unitaire ou d'integration (`tests/README.md` seul). Pas de scenario pour LLM OK/lent/Hors ligne.
- Pas de framework de mock HTTP (`respx`, `responses`, `pytest-httpserver`...), donc impossible aujourd'hui de simuler Ollama.
- Les scripts `.bat/.ps1` sous `scripts/` ne sont pas branches a la CI et reposent sur un environnement manuel.

### Journaux et observabilite (Majeur)
- `print()` un peu partout (`app/main.py`, `app/services/game_state.py`, `app/services/ws_manager.py`, `app/routes/master.py`...), sans niveau, sans structure JSON, sans correlation. Impossible de suivre un flux LLM multi-appels ou de rattacher un event WS a une requete HTTP.
- Pas de middleware FastAPI de logging, pas d'idempotence / correlation id pour les requetes LLM, pas de capture des timings.
- Les erreurs critiques (`run_llm`, `generate_indice`) ne sont pas journalisees; on ne sait pas pourquoi un stub est renvoye.

### Gestion des secrets et donnees (Majeur)
- `.env` est present dans le repo avec `MJ_TOKEN`, `MJ_PASSWORD`, etc., bien que `.gitignore` l'inclue: risque de commit accidentel et de diffusion de secrets.
- `app/config/settings.py` contient des valeurs par defaut risquées (`MJ_TOKEN="changeme-super-secret"`, etc.), et rien n'empeche qu'elles soient utilisees en prod si `.env` n'est pas charge.
- `app/data/*.json` (players.json, game_state.json, verdict.json, etc.) sont versionnes; ils contiennent des hash PBKDF2, des sessions MJ (`__mj_sessions__`), des enveloppes assignes. Ces fichiers devraient etre ignores (`git`) et/ou anonymises.

### CI / CD (Majeur)
- Workflow `ci-backend.yml` lance `pytest -q` mais `requirements.txt` n'installe pas `pytest`, donc le job echoue toujours.
- Pas de separation dev/prod des dependances; aucune verification de lint, format ou securite.
- Aucun cache pip, pas de strategy pour les secrets CI (e.g. variables LLM).

### Docker / scripts / dev tooling (Mineur)
- Aucun Dockerfile ni docker-compose pour "sante" du service, malgre la dependance a Ollama. Il est donc difficile de lancer un environnement reprenant les attentes (FastAPI + Ollama) sous CI ou staging.
- `run.bat` force Windows + `.venv`; pas d'equivalent cross-platform ou Makefile.
- Donnees runtime dans `app/data` risquent de diverger entre dev/prod faute de mecanisme de reseed.

## Plan d'actions priorise

1. **Renforcer les appels LLM (Critique)**  
   - Introduire un client LLM centralise avec retries exponentiels, backoff et jitter (`tenacity` ou `httpx.RetryTransport`).  
   - Normaliser les erreurs (`LLMError`), propager un champ `error` comprehensible et journaliser chaque echec avec contexte/correlation id.  
   - Refuser de renvoyer un stub silencieux: retourner une 503 ou remonter un flag explicite traite par le front.

2. **Mettre en place les tests et la CI (Critique)**  
   - Ajouter `pytest`, `pytest-asyncio`, `respx` (ou equivalent) dans un `requirements-dev.txt` et mettre a jour `ci-backend.yml`.  
   - Ecrire des tests d'integration couvrant LLM OK / timeout / indisponible en mockant `requests.post` ou via `respx`.  
   - Fournir des fixtures pour simuler les JSON de retour Ollama (chat et generate).

3. **Refondre la journalisation (Majeur)**  
   - Configurer `logging` ou `structlog` des le demarrage (`app/main.py`) avec format JSON et correlation id (ex: `X-Request-ID`).  
   - Envelopper les appels LLM pour logguer `prompt_id`, delai, statut http, message d'erreur.  
   - Remplacer les `print()` par des logs de niveau adapte (info/warning/error) afin d'alimenter un SIEM ou un traceur.

4. **Assainir secrets et donnees (Majeur)**  
   - Supprimer `.env` du repo, fournir un `.env.example`, et renforcer la charge de `settings` (valeurs obligatoires en prod, detection `changeme`).  
   - Ajouter `app/data/*.json`, `tmp_*.json`, `*.db` au `.gitignore`; stocker des fixtures anonymisees ailleurs (`docs/samples/`).  
   - Revoir la strategie de stockage des sessions MJ pour eviter de commit des tokens (ex: stockage in-memory ou redis en prod).

5. **Solidifier la CI / tooling (Majeur)**  
   - CI: ajouter installation des dependances dev, execution des tests, eventuelle verification `ruff`/`mypy`.  
   - Ajouter un Dockerfile (FastAPI + uvicorn) et un docker-compose de stack locale (backend + Ollama mock) pour faciliter la reproduction des problemes de latence.  
   - Ajouter une commande `make test` ou `poetry run task` documentee.

6. **Actions complementaires (Mineur)**  
   - Documenter clairement comment demarrer un Ollama de test (mode offline) et comment pointer vers un stub HTTP.  
   - Mettre en place des scripts de seed/reset qui n'ecrivent pas directement dans le repo (dossier `runtime/` ignored).  
   - Harmoniser les endpoints de health check LLM (`/health/llm`, `/game/test_llm`) pour qu'ils propagent l'etat reel du client LLM.

## Propositions de PR
1. **fix/llm-timeouts**  
   - Nouveau client LLM resilient (retries exponentiels, backoff, instrumentation).  
   - Gestion d'erreur normalisee (exceptions, codes HTTP, champ `error`).  
   - Logs contextualises (latence, statut, correlation id).

2. **feat/integration-tests-llm**  
   - Ajout de dependances test (`pytest`, `respx`, `pytest-asyncio`).  
   - Tests couvrant LLM OK / timeout / indisponible pour `generate_indice` et `run_llm`.  
   - Fixtures de donnees + configuration pour executer `pytest` en CI.

3. **chore/logging**  
   - Configuration `logging` globale (format JSON, niveaux).  
   - Remplacement des `print()` par des logs structurels, injection d'un middleware `RequestId`.  
   - Documentation sur la consommation des logs.

4. **chore/ci-hardening**  
   - Mise a jour `ci-backend.yml` (installation deps dev, cache pip, jobs failing the PR).  
   - Ajout d'un Dockerfile + compose de dev (backend + mock LLM).  
   - Nettoyage `.env`, ajout `.env.example`, ignore des fichiers runtime (`app/data`, `tmp_*.json`).
