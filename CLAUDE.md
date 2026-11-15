# Assistant IA microfinance

Assistant IA connecte a des donnees de microfinance via un serveur MCP, avec permissions par role et journal d'audit.

## Commandes
- Demarrer la base : `docker compose up -d`
- Reinitialiser la base (efface tout) : `docker compose down -v && docker compose up -d`
- Installer : `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Generer les donnees : `python data/generate.py` (ajouter `--dry-run` pour tester sans base)
- Acceder a la base : `docker exec -it microfinance-db psql -U microfinance`
- Serveur MCP (stdio) : `MCP_USER_ID=3 python mcp_server/server.py` (ids : 1-2 agent_terrain, 3 responsable, 4 auditeur ; base sur le port 5433, surchargeable via `DATABASE_URL`)
- Demo des roles (via MCP, base de dev) : `python scripts/demo_roles.py` ; captures pour le README : `pip install -r requirements-dev.txt && python scripts/make_screenshots.py`
- Tests : `source .venv/bin/activate && python -m pytest` (la base Docker doit tourner sur le port 5433 ; les tests creent puis suppriment une base `microfinance_test`, la base de dev n'est pas touchee)

## Regles du projet
- Donnees 100 % synthetiques, jamais de donnees reelles d'un employeur ou d'un client
- Montants en francs CFA (XOF), stockes en entiers
- Serveur MCP : peu d'outils, descriptions claires, reponses courtes
- Chaque appel d'outil est enregistre dans `audit_log`
- Les permissions par role (agent_terrain, responsable, auditeur) sont verifiees cote serveur, jamais dans le prompt (matrice `PERMISSIONS` dans `mcp_server/server.py`)

## Pieges
- `db/schema.sql` n'est applique qu'a la premiere creation du volume Docker : apres une modification du schema, utiliser la commande de reinitialisation
- La dimension de `policy_chunks.embedding` (1024) doit correspondre au modele d'embeddings choisi
