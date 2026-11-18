"""Évaluation de l'assistant : 10 cas (evals/cases.json) joués avec un modèle Claude et le serveur MCP.

Pour chaque cas : le modèle reçoit la question et les outils du serveur MCP (lancé en stdio, base de
dev, MCP_USER_ID=3 = responsable). On compare ensuite :
- l'outil : premier outil appelé == outil_attendu (null = aucun outil ne doit être appelé) ;
- la réponse : valeurs calculées par le champ `sql` (lues dans la base au moment du test) présentes
  dans la réponse, sauf colonnes préfixées par « _ » (simples gardes) ; et, si `mots_cles` existe,
  au moins un de ces mots/expressions. Casse, accents et espaces sont ignorés.

Usage : python evals/run_evals.py --dry-run     # valide les cas et affiche les valeurs attendues (sans LLM)
        ANTHROPIC_API_KEY=... python evals/run_evals.py [--modele claude-haiku-5-5]

Prérequis : docker compose up -d, python data/generate.py, pip install -r requirements-dev.txt.
Code de sortie : 0 si 10/10, 1 sinon. Chaque appel d'outil est journalisé dans audit_log (base de dev).
Données 100 % fictives.
"""

import argparse
import asyncio
import json
import os
import sys
import unicodedata
from pathlib import Path

import psycopg

RACINE = Path(__file__).resolve().parent.parent
SERVER = RACINE / "mcp_server" / "server.py"
CASES = Path(__file__).resolve().parent / "cases.json"
DEFAULT_URL = "postgresql://microfinance:microfinance@localhost:5433/microfinance"
MODELE_PAR_DEFAUT = "claude-haiku-5-5"
MAX_TOURS = 6
SYSTEME = (
    "Tu es l'assistant d'une institution de microfinance. Réponds en français, brièvement, "
    "uniquement à partir des outils fournis. Si aucun outil ne permet de répondre ou d'agir, "
    "dis-le clairement. Si la question est ambiguë, demande une précision."
)


def normaliser(texte) -> str:
    """Minuscules, sans accents ni espaces (y compris insécables) : « 1 515 000 » -> « 1515000 »."""
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", str(texte)) if unicodedata.category(c) != "Mn"
    )
    return "".join(sans_accents.lower().split())


def charger_cas() -> list[dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))


def valeurs_attendues(conn, cas) -> dict:
    """Exécute le champ `sql` du cas : retourne {colonne: valeur} (une seule ligne attendue)."""
    curseur = conn.execute(cas["sql"])
    ligne = curseur.fetchone()
    if ligne is None:
        raise ValueError("la requête sql ne retourne aucune ligne")
    return dict(zip([c.name for c in curseur.description], ligne))


def evaluer(cas, valeurs, outils_appeles, reponse) -> list[str]:
    """Retourne la liste des raisons d'échec (vide si le cas est réussi)."""
    echecs = []
    attendu = cas["outil_attendu"]
    premier = outils_appeles[0] if outils_appeles else None
    if premier != attendu:
        echecs.append(f"outil : attendu {attendu or 'aucun'}, obtenu {premier or 'aucun'}")
    texte = normaliser(reponse)
    manquantes = [
        str(v) for k, v in valeurs.items() if not k.startswith("_") and normaliser(v) not in texte
    ]
    if manquantes:
        echecs.append("réponse : valeur(s) absente(s) " + ", ".join(manquantes))
    mots = cas.get("mots_cles")
    if mots and not any(normaliser(m) in texte for m in mots):
        echecs.append("réponse : aucun des mots attendus (" + ", ".join(mots) + ")")
    return echecs


async def poser_question(llm, modele, session, outils, question):
    """Boucle outil/réponse avec le modèle. Retourne (outils appelés dans l'ordre, texte final)."""
    messages = [{"role": "user", "content": question}]
    appeles = []
    for _ in range(MAX_TOURS):
        rep = llm.messages.create(
            model=modele, max_tokens=1024, system=SYSTEME, tools=outils, messages=messages
        )
        if rep.stop_reason != "tool_use":
            return appeles, "".join(b.text for b in rep.content if b.type == "text")
        messages.append({"role": "assistant", "content": rep.content})
        resultats = []
        for bloc in (b for b in rep.content if b.type == "tool_use"):
            appeles.append(bloc.name)
            retour = await session.call_tool(bloc.name, bloc.input)
            resultats.append({
                "type": "tool_result",
                "tool_use_id": bloc.id,
                "content": retour.content[0].text if retour.content else "",
            })
        messages.append({"role": "user", "content": resultats})
    return appeles, "(aucune réponse finale : trop d'appels d'outils)"


async def jouer(cas_et_valeurs, modele, url):
    import anthropic
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    llm = anthropic.Anthropic()
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        env={**os.environ, "MCP_USER_ID": "3", "DATABASE_URL": url},
    )
    resultats = []
    async with stdio_client(params) as (lecture, ecriture):
        async with ClientSession(lecture, ecriture) as session:
            await session.initialize()
            outils = [
                {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
                for t in (await session.list_tools()).tools
            ]
            for cas, valeurs in cas_et_valeurs:
                try:
                    appeles, reponse = await poser_question(
                        llm, modele, session, outils, cas["question"]
                    )
                    echecs = evaluer(cas, valeurs, appeles, reponse)
                except Exception as e:  # une panne ne doit pas arrêter les autres cas
                    appeles, reponse, echecs = [], "", [f"erreur : {type(e).__name__}: {e}"]
                resultats.append((cas, appeles, reponse, echecs))
    return resultats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="valide les cas sans appeler le LLM")
    parser.add_argument("--modele", default=os.environ.get("EVAL_MODEL", MODELE_PAR_DEFAUT))
    args = parser.parse_args()

    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    cas_et_valeurs, invalides = [], []
    with psycopg.connect(url) as conn:
        for cas in charger_cas():
            try:
                cas_et_valeurs.append((cas, valeurs_attendues(conn, cas)))
            except Exception as e:
                conn.rollback()
                invalides.append((cas["id"], str(e).splitlines()[0]))
    if invalides:
        print("Cas invalides (sql) :")
        for id_, raison in invalides:
            print(f"  - {id_} : {raison}")
        return 1

    if args.dry_run:
        for cas, valeurs in cas_et_valeurs:
            print(f"{cas['id']} [{cas['categorie']}] outil={cas['outil_attendu'] or 'aucun'}")
            print(f"    {cas['question']}")
            print(f"    attendu : {valeurs}")
        print(f"\n{len(cas_et_valeurs)} cas valides (aucun appel LLM).")
        return 0

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY absente (ou utiliser --dry-run pour valider les cas sans LLM).")

    resultats = asyncio.run(jouer(cas_et_valeurs, args.modele, url))
    for cas, appeles, _, echecs in resultats:
        print(f"{'OK  ' if not echecs else 'RATE'} {cas['id']}  (outils : {', '.join(appeles) or 'aucun'})")
    ratés = [r for r in resultats if r[3]]
    print(f"\nScore : {len(resultats) - len(ratés)}/{len(resultats)}  (modèle {args.modele})")
    for cas, appeles, reponse, echecs in ratés:
        print(f"\n--- {cas['id']} : {cas['question']}")
        for e in echecs:
            print(f"  * {e}")
        print(f"  réponse : {reponse.strip()[:300] or '(vide)'}")
    return 1 if ratés else 0


if __name__ == "__main__":
    sys.exit(main())
