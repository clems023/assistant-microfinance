# Assistant IA microfinance

Projet vitrine : un assistant IA qui repond a des questions sur un portefeuille de microfinance, via un serveur MCP, avec permissions par role et journal d'audit. Donnees 100 % synthetiques.

## Demarrage

```bash
docker compose up -d
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python data/generate.py
```

## Structure

- `db/schema.sql` : schema PostgreSQL (clients, prets, remboursements, utilisateurs, journal d'audit, documents pour le RAG)
- `data/generate.py` : generateur de donnees fictives
- `mcp_server/server.py` : serveur MCP (rechercher_client, statut_pret, prets_en_retard)
- `evals/` : jeu de questions-tests (a venir)
