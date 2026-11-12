"""Serveur MCP de l'assistant microfinance (donnees 100 % synthetiques).

Trois outils : rechercher_client, statut_pret, prets_en_retard.

Securite (cote serveur, jamais dans le prompt) :
- l'identite vient de la variable d'environnement MCP_USER_ID (id dans app_users) ;
  le role est lu en base, jamais fourni par le modele ;
- sans identite valide, tout appel est refuse ;
- pour l'instant, tous les roles peuvent appeler les 3 outils (restrictions a venir).

Chaque appel (ok, refuse ou erreur) est enregistre dans audit_log.

Lancement : MCP_USER_ID=3 python mcp_server/server.py
"""

import os
from datetime import date

import psycopg
from mcp.server.mcpserver import MCPServer
from psycopg.types.json import Jsonb

DEFAULT_URL = "postgresql://microfinance:microfinance@localhost:5433/microfinance"
MAX_LIGNES = 10

mcp = MCPServer(
    "assistant-microfinance",
    instructions="Consulter clients et prets d'un portefeuille de microfinance. Montants en XOF.",
)


def fmt_xof(montant: int) -> str:
    return f"{montant:,}".replace(",", " ") + " XOF"


def connecter():
    return psycopg.connect(os.environ.get("DATABASE_URL", DEFAULT_URL))


def lire_acteur(conn):
    """Retourne (user_id, role) depuis MCP_USER_ID, ou None si inconnu."""
    brut = os.environ.get("MCP_USER_ID", "")
    if not brut.isdigit():
        return None
    ligne = conn.execute("SELECT id, role FROM app_users WHERE id = %s", (int(brut),)).fetchone()
    return ligne


def executer(outil: str, arguments: dict, impl):
    """Execute impl(conn, user_id, role) -> (status, texte) et journalise toujours l'appel."""
    with connecter() as conn:
        acteur = lire_acteur(conn)
        user_id, role = acteur if acteur else (None, "inconnu")
        try:
            if acteur is None:
                status, texte = "refuse", "Acces refuse : utilisateur non identifie."
            else:
                status, texte = impl(conn, user_id, role)
        except Exception:
            conn.rollback()
            status, texte = "erreur", "Erreur interne, reessayez plus tard."
        conn.execute(
            "INSERT INTO audit_log (user_id, role, tool_name, arguments, status, resume)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, role, outil, Jsonb(arguments), status, texte[:200]),
        )
    return texte


@mcp.tool()
def rechercher_client(nom: str) -> str:
    """Cherche des clients par nom (recherche partielle). Retourne au plus 5 resultats."""

    def impl(conn, user_id, role):
        motif = "%" + nom.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        lignes = conn.execute(
            "SELECT id, nom, ville, activite FROM clients"
            " WHERE nom ILIKE %s ORDER BY nom LIMIT 5",
            (motif,),
        ).fetchall()
        if not lignes:
            return "ok", "Aucun client trouve."
        return "ok", "\n".join(
            f"#{i} {n} - {v}, {a}" for i, n, v, a in lignes
        )

    if len(nom.strip()) < 2:
        return executer("rechercher_client", {"nom": nom},
                        lambda *_: ("erreur", "Nom trop court (2 caracteres minimum)."))
    return executer("rechercher_client", {"nom": nom}, impl)


@mcp.tool()
def statut_pret(loan_id: int) -> str:
    """Donne le statut d'un pret : montant, statut, echeances payees/restantes, prochain paiement du."""

    def impl(conn, user_id, role):
        ligne = conn.execute(
            "SELECT c.nom, l.montant, l.statut"
            " FROM loans l JOIN clients c ON c.id = l.client_id WHERE l.id = %s",
            (loan_id,),
        ).fetchone()
        if ligne is None:
            return "ok", "Pret introuvable."
        nom, montant, statut = ligne
        payees, restantes = conn.execute(
            "SELECT count(*) FILTER (WHERE montant_paye >= montant_du),"
            " count(*) FILTER (WHERE montant_paye < montant_du)"
            " FROM repayments WHERE loan_id = %s",
            (loan_id,),
        ).fetchone()
        # Prochain paiement du : la plus ancienne echeance non soldee (echue ou a venir).
        suivante = conn.execute(
            "SELECT date_echeance, montant_du - montant_paye FROM repayments"
            " WHERE loan_id = %s AND montant_paye < montant_du"
            " ORDER BY date_echeance LIMIT 1",
            (loan_id,),
        ).fetchone()
        texte = (
            f"Pret #{loan_id} ({nom}) : {fmt_xof(montant)}, {statut}."
            f" Echeances : {payees} payee(s), {restantes} restante(s)."
        )
        if suivante:
            texte += f" Prochain paiement du : {fmt_xof(suivante[1])} le {suivante[0]}."
        else:
            texte += " Aucun paiement du."
        return "ok", texte

    return executer("statut_pret", {"loan_id": loan_id}, impl)


@mcp.tool()
def prets_en_retard() -> str:
    """Liste les prets en retard ou en defaut (10 plus anciens impayes). Sans argument."""

    def impl(conn, user_id, role):
        base = (
            " FROM loans l JOIN clients c ON c.id = l.client_id"
            " JOIN repayments r ON r.loan_id = l.id AND r.date_echeance < %s"
            "  AND r.montant_paye < r.montant_du"
            " WHERE l.statut IN ('en_retard', 'defaut')"
        )
        args = [date.today()]
        total = conn.execute(
            "SELECT count(DISTINCT l.id)" + base, args
        ).fetchone()[0]
        if total == 0:
            return "ok", "Aucun pret en retard."
        lignes = conn.execute(
            "SELECT l.id, c.nom, l.statut, sum(r.montant_du - r.montant_paye),"
            " %s - min(r.date_echeance)" + base +
            " GROUP BY l.id, c.nom, l.statut ORDER BY min(r.date_echeance) LIMIT " + str(MAX_LIGNES),
            [date.today(), *args],
        ).fetchall()
        corps = "\n".join(
            f"#{i} {n} - {s}, {fmt_xof(int(m))} impaye, {j} j de retard"
            for i, n, s, m, j in lignes
        )
        suite = f"\n... et {total - len(lignes)} autre(s)." if total > len(lignes) else ""
        return "ok", f"{total} pret(s) en retard :\n{corps}{suite}"

    return executer("prets_en_retard", {}, impl)


if __name__ == "__main__":
    mcp.run()
