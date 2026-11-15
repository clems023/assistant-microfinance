"""Test de bout en bout : le serveur est lance en sous-processus et pilote via le protocole MCP (stdio).

Utilise le client du SDK `mcp` (ClientSession + stdio_client) et la base de test (voir conftest.py).
Lancement : python -m pytest tests/test_e2e_mcp.py
"""

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from conftest import AGENT_1, RESPONSABLE, TEST_URL

SERVER = Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"
OUTILS_ATTENDUS = {"rechercher_client", "statut_pret", "prets_en_retard", "journal_audit"}
TIMEOUT = 30


async def session_mcp(user_id: str, scenario):
    """Demarre le serveur avec MCP_USER_ID=user_id et execute scenario(session)."""
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        env={**os.environ, "MCP_USER_ID": user_id, "DATABASE_URL": TEST_URL},
    )
    async with stdio_client(params) as (lecture, ecriture):
        async with ClientSession(lecture, ecriture) as session:
            await session.initialize()
            return await scenario(session)


def executer(user_id: str, scenario):
    return asyncio.run(asyncio.wait_for(session_mcp(user_id, scenario), TIMEOUT))


def test_le_serveur_expose_exactement_4_outils():
    async def lister(session):
        return [t.name for t in (await session.list_tools()).tools]

    noms = executer(AGENT_1, lister)
    assert len(noms) == 4
    assert set(noms) == OUTILS_ATTENDUS


def test_statut_pret_depend_du_role_via_mcp():
    async def pret_2(session):
        resultat = await session.call_tool("statut_pret", {"loan_id": 2})
        return resultat.content[0].text

    # Le pret 2 appartient a l'agent 2.
    vu_par_agent_1 = executer(AGENT_1, pret_2)
    vu_par_responsable = executer(RESPONSABLE, pret_2)
    assert vu_par_agent_1 == "Prêt introuvable."
    assert vu_par_responsable.startswith("Prêt #2")
    assert vu_par_agent_1 != vu_par_responsable
