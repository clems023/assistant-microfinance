# Assistant IA microfinance

Projet vitrine : un assistant IA qui repond a des questions sur un portefeuille de microfinance, via un serveur MCP, avec permissions par role et journal d'audit. Donnees 100 % synthetiques.

## Demarrage

```bash
docker compose up -d
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python data/generate.py
```

## Serveur MCP

Lancement (transport stdio) :

```bash
MCP_USER_ID=3 python mcp_server/server.py
```

`MCP_USER_ID` est l'id d'un utilisateur de la table `app_users` : 1 et 2 agents terrain, 3 responsable, 4 auditeur. Le role est lu en base par le serveur, jamais fourni par le modele. La base est jointe sur `localhost:5433` (surcharge via `DATABASE_URL`).

### Permissions

| Outil | agent_terrain | responsable | auditeur |
|---|---|---|---|
| `rechercher_client(nom)` | clients ayant un de ses prets | tout | tout |
| `statut_pret(loan_id)` | ses prets (sinon « Pret introuvable. ») | tout | tout |
| `prets_en_retard()` | ses prets | tout | tout |
| `journal_audit(limite)` | refuse | refuse | oui |

Chaque appel, y compris refuse ou en erreur, ajoute une ligne dans `audit_log`.

> **Limite connue :** l'identite vient d'une variable d'environnement fixee par celui qui configure le client. Ce n'est pas une authentification : le modele ne peut pas changer de role, mais quiconque edite la configuration peut choisir n'importe quel id. Une vraie authentification (jeton, OAuth) reste a faire.

### Brancher un client MCP

Remplacer `/chemin/vers/assistant-microfinance` par le chemin absolu du projet (le venv doit etre installe et la base demarree).

Claude Code :

```bash
claude mcp add microfinance -e MCP_USER_ID=3 -- /chemin/vers/assistant-microfinance/.venv/bin/python /chemin/vers/assistant-microfinance/mcp_server/server.py
```

Autre client MCP (Claude Desktop, etc.), fichier de configuration JSON :

```json
{
  "mcpServers": {
    "microfinance": {
      "command": "/chemin/vers/assistant-microfinance/.venv/bin/python",
      "args": ["/chemin/vers/assistant-microfinance/mcp_server/server.py"],
      "env": { "MCP_USER_ID": "3" }
    }
  }
}
```

Pour tester un autre role, changer `MCP_USER_ID` (un serveur = une identite).

## Tests

```bash
source .venv/bin/activate && python -m pytest
```

La base Docker doit tourner (port 5433). Les tests creent une base separee `microfinance_test`, la remplissent de donnees fictives puis la suppriment : la base de dev n'est pas modifiee.

## Structure

- `db/schema.sql` : schema PostgreSQL (clients, prets, remboursements, utilisateurs, journal d'audit, documents pour le RAG)
- `data/generate.py` : generateur de donnees fictives
- `mcp_server/server.py` : serveur MCP (rechercher_client, statut_pret, prets_en_retard, journal_audit)
- `tests/` : tests pytest des permissions par role
- `evals/` : jeu de questions-tests (a venir)
