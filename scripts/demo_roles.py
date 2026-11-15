"""Démo : mêmes questions posées à l'assistant en tant qu'agent_terrain puis responsable.

Les appels passent par le protocole MCP (serveur lancé en stdio, client du SDK `mcp`) sur la base
de dev. Prérequis : docker compose up -d, puis python data/generate.py.

Usage : python scripts/demo_roles.py
        python scripts/demo_roles.py --largeur 38 --max-lignes 4   # affichage compact (captures)

--max-lignes ne fait qu'abréger l'affichage (marqueur « [...] ») : les réponses viennent du serveur.
Données 100 % fictives. Chaque appel est journalisé dans audit_log de la base de dev.
"""

import argparse
import asyncio
import os
import sys
import textwrap
from itertools import zip_longest
from pathlib import Path

import psycopg
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"
DEFAULT_URL = "postgresql://microfinance:microfinance@localhost:5433/microfinance"
URL = os.environ.get("DATABASE_URL", DEFAULT_URL)

AGENT = ("agent_terrain (id 1)", "1")
RESPONSABLE = ("responsable (id 3)", "3")
LARGEUR = 62  # largeur de chaque colonne (modifiable avec --largeur)


def pret_d_un_autre_agent() -> int:
    """Un prêt en retard appartenant à l'agent 2 (donc hors portefeuille de l'agent 1)."""
    with psycopg.connect(URL) as conn:
        ligne = conn.execute(
            "SELECT id FROM loans WHERE agent_id = 2 AND statut IN ('en_retard', 'defaut')"
            " ORDER BY id LIMIT 1"
        ).fetchone()
    if ligne is None:
        sys.exit("Aucun prêt en retard pour l'agent 2 : lancer d'abord python data/generate.py")
    return ligne[0]


async def poser_questions(user_id: str, questions):
    """Démarre le serveur avec MCP_USER_ID=user_id et retourne la réponse à chaque question."""
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        env={**os.environ, "MCP_USER_ID": user_id, "DATABASE_URL": URL},
    )
    async with stdio_client(params) as (lecture, ecriture):
        async with ClientSession(lecture, ecriture) as session:
            await session.initialize()
            return [
                (await session.call_tool(outil, args)).content[0].text
                for outil, args in questions
            ]


def colonne(texte: str, largeur: int, max_lignes: int | None) -> list[str]:
    brutes = texte.splitlines() or [""]
    if max_lignes and len(brutes) > max_lignes:
        brutes = brutes[:max_lignes] + ["[...]"]
    lignes = []
    for ligne in brutes:
        lignes += textwrap.wrap(ligne, largeur, subsequent_indent="  ") or [""]
    return lignes


def cote_a_cote(titre: str, gauche: str, droite: str, largeur: int, max_lignes: int | None):
    print(f"\n{titre}")
    print(f"{AGENT[0]:<{largeur}} | {RESPONSABLE[0]}")
    print("-" * largeur + "-+-" + "-" * largeur)
    colonnes = zip_longest(
        colonne(gauche, largeur, max_lignes), colonne(droite, largeur, max_lignes), fillvalue=""
    )
    for g, d in colonnes:
        print(f"{g:<{largeur}} | {d}")


async def main(largeur: int, max_lignes: int | None):
    loan_id = pret_d_un_autre_agent()
    questions = [("prets_en_retard", {}), ("statut_pret", {"loan_id": loan_id})]
    reponses_agent = await poser_questions(AGENT[1], questions)
    reponses_resp = await poser_questions(RESPONSABLE[1], questions)

    print("DÉMO : mêmes questions, deux rôles (via le protocole MCP)")
    cote_a_cote("Question 1 : prets_en_retard()", reponses_agent[0], reponses_resp[0],
                largeur, max_lignes)
    cote_a_cote(
        f"Question 2 : statut_pret({loan_id})  (prêt d'un autre agent)",
        reponses_agent[1],
        reponses_resp[1],
        largeur,
        max_lignes,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--largeur", type=int, default=LARGEUR, help="largeur de chaque colonne")
    parser.add_argument("--max-lignes", type=int, default=None,
                        help="n'afficher que les N premières lignes de chaque réponse")
    args = parser.parse_args()
    asyncio.run(main(args.largeur, args.max_lignes))
