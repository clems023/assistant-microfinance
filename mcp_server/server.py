"""Serveur MCP de l'assistant microfinance (donnees 100 % synthetiques).

Quatre outils : rechercher_client, statut_pret, prets_en_retard, journal_audit.

Securite (cote serveur, jamais dans le prompt) :
- l'identite vient de la variable d'environnement MCP_USER_ID (id dans app_users) ;
  le role est lu en base, jamais fourni par le modele ;
- sans identite valide, tout appel est refuse ;
- PERMISSIONS dit quel role peut appeler quel outil (verifie dans executer) ;
- agent_terrain ne voit que ses prets (loans.agent_id) et les clients qui en ont au moins un ;
  le pret d'un autre agent recoit le meme message que « Pret introuvable » ;
- responsable : acces complet ; auditeur : lecture complete + journal_audit (lui seul).

Chaque appel (ok, refuse ou erreur) est enregistre dans audit_log.

Lancement : MCP_USER_ID=3 python mcp_server/server.py
"""

import json
import os
from datetime import date

import psycopg
from mcp.server.mcpserver import MCPServer
from psycopg.types.json import Jsonb

DEFAULT_URL = "postgresql://microfinance:microfinance@localhost:5433/microfinance"
MAX_LIGNES = 10
MAX_JOURNAL = 50
INTROUVABLE = "Pret introuvable."

TOUS_LES_ROLES = {"agent_terrain", "responsable", "auditeur"}
# Matrice outil -> roles autorises. Un outil absent de la table est refuse a tous.
PERMISSIONS = {
    "rechercher_client": TOUS_LES_ROLES,
    "statut_pret": TOUS_LES_ROLES,
    "prets_en_retard": TOUS_LES_ROLES,
    "journal_audit": {"auditeur"},
}

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
    """Execute impl(conn, user_id, role) et journalise toujours l'appel.

    impl retourne (status, texte) ou (status, texte, resume_audit) : le resume d'audit peut etre
    plus precis que le texte renvoye au modele (ex. pret hors portefeuille).
    """
    with connecter() as conn:
        acteur = lire_acteur(conn)
        user_id, role = acteur if acteur else (None, "inconnu")
        resume = None
        try:
            if acteur is None:
                status, texte = "refuse", "Acces refuse : utilisateur non identifie."
            elif role not in PERMISSIONS.get(outil, set()):
                status, texte = "refuse", "Acces refuse : role non autorise pour cet outil."
            else:
                status, texte, *reste = impl(conn, user_id, role)
                resume = reste[0] if reste else None
        except Exception:
            conn.rollback()
            status, texte = "erreur", "Erreur interne, reessayez plus tard."
        conn.execute(
            "INSERT INTO audit_log (user_id, role, tool_name, arguments, status, resume)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, role, outil, Jsonb(arguments), status, (resume or texte)[:200]),
        )
    return texte


@mcp.tool()
def rechercher_client(nom: str) -> str:
    """Cherche des clients par nom (recherche partielle). Retourne au plus 5 resultats."""

    def impl(conn, user_id, role):
        motif = "%" + nom.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filtre, params = "", []
        if role == "agent_terrain":  # seulement les clients ayant un de ses prets
            filtre = (" AND EXISTS (SELECT 1 FROM loans l"
                      " WHERE l.client_id = c.id AND l.agent_id = %s)")
            params = [user_id]
        lignes = conn.execute(
            "SELECT c.id, c.nom, c.ville, c.activite FROM clients c"
            " WHERE c.nom ILIKE %s" + filtre + " ORDER BY c.nom LIMIT 5",
            [motif, *params],
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
            "SELECT c.nom, l.montant, l.statut, l.agent_id"
            " FROM loans l JOIN clients c ON c.id = l.client_id WHERE l.id = %s",
            (loan_id,),
        ).fetchone()
        if ligne is None:
            return "ok", INTROUVABLE
        nom, montant, statut, agent_id = ligne
        if role == "agent_terrain" and agent_id != user_id:
            # Meme texte que « introuvable » : ne pas reveler que le pret existe.
            return "refuse", INTROUVABLE, f"Pret #{loan_id} hors portefeuille (agent {user_id})"
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
        if role == "agent_terrain":
            base += " AND l.agent_id = %s"
            args.append(user_id)
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


@mcp.tool()
def journal_audit(limite: int = 10) -> str:
    """Reserve a l'auditeur : derniers appels d'outils enregistres (10 par defaut, 50 max)."""

    def impl(conn, user_id, role):
        n = max(1, min(limite, MAX_JOURNAL))
        lignes = conn.execute(
            "SELECT id, occurred_at, user_id, role, tool_name, status, arguments"
            " FROM audit_log ORDER BY id DESC LIMIT %s",
            (n,),
        ).fetchall()
        if not lignes:
            return "ok", "Journal vide."
        return "ok", "\n".join(
            f"#{i} {t:%Y-%m-%d %H:%M} user={u} {r} {o} {st}"
            f" {json.dumps(a, ensure_ascii=False)}"
            for i, t, u, r, o, st, a in lignes
        ), f"{len(lignes)} ligne(s) du journal consultee(s)"

    return executer("journal_audit", {"limite": limite}, impl)


if __name__ == "__main__":
    mcp.run()
