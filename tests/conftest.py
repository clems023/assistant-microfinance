"""Fixtures de test : base PostgreSQL dediee `microfinance_test` (donnees 100 % fictives).

Necessite le conteneur Docker (docker compose up -d, port 5433). La base de dev n'est jamais touchee :
on cree une base separee dans le meme serveur, on y applique db/schema.sql, puis on la supprime.
Surcharge possible : TEST_ADMIN_URL (connexion a la base `postgres` du serveur).
"""

import os
from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest

ADMIN_URL = os.environ.get(
    "TEST_ADMIN_URL", "postgresql://microfinance:microfinance@localhost:5433/postgres"
)
TEST_DB = "microfinance_test"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + "/" + TEST_DB
SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"

# Ids des utilisateurs de test (ordre d'insertion dans app_users).
AGENT_1, AGENT_2, RESPONSABLE, AUDITEUR = "1", "2", "3", "4"

# Valeurs qui ne doivent jamais apparaitre dans les reponses des outils.
TELEPHONE = "+228 90 00 00 00"
NOTE_SECRETE = "NOTE-SECRETE-AGENT"


def _jours(n: int) -> date:
    return date.today() + timedelta(days=n)


def _seed(conn):
    conn.execute(
        "INSERT INTO app_users (nom, role) VALUES"
        " ('Agent Un', 'agent_terrain'), ('Agent Deux', 'agent_terrain'),"
        " ('Resp', 'responsable'), ('Audit', 'auditeur')"
    )
    conn.execute(
        "INSERT INTO clients (nom, telephone, ville, activite, date_inscription) VALUES"
        " ('Awa Alpha', %(t)s, 'Lome', 'commerce', %(d)s),"
        " ('Kofi Beta', %(t)s, 'Kara', 'couture', %(d)s),"
        " ('Ama Alpha SansPret', %(t)s, 'Atakpame', 'transport', %(d)s),"
        " ('Esi Gamma', %(t)s, 'Kpalime', 'artisanat', %(d)s)",
        {"t": TELEPHONE, "d": _jours(-900)},
    )
    # pret 1 : agent 1, en cours ; pret 2 : agent 2, en retard ; pret 3 : agent 1, defaut.
    conn.execute(
        "INSERT INTO loans (client_id, agent_id, montant, taux_annuel, duree_mois,"
        " date_octroi, statut, notes_agent) VALUES"
        " (1, 1, 500000, 20, 3, %s, 'en_cours', %s),"
        " (2, 2, 800000, 20, 3, %s, 'en_retard', %s),"
        " (4, 1, 300000, 20, 2, %s, 'defaut', %s)",
        (_jours(-40), NOTE_SECRETE, _jours(-100), NOTE_SECRETE, _jours(-200), NOTE_SECRETE),
    )
    # (loan_id, numero, jours_avant_ou_apres_aujourdhui, du, paye)
    echeances = [
        (1, 1, -10, 180000, 180000), (1, 2, 20, 180000, 0), (1, 3, 50, 180000, 0),
        (2, 1, -70, 290000, 290000), (2, 2, -40, 290000, 0), (2, 3, -10, 290000, 0),
        (3, 1, -170, 160000, 160000), (3, 2, -140, 160000, 0),
    ]
    for loan_id, numero, jours, du, paye in echeances:
        conn.execute(
            "INSERT INTO repayments (loan_id, echeance_numero, date_echeance, montant_du,"
            " montant_paye, date_paiement) VALUES (%s, %s, %s, %s, %s, %s)",
            (loan_id, numero, _jours(jours), du, paye, _jours(jours) if paye else None),
        )


@pytest.fixture(scope="session", autouse=True)
def base_test():
    admin = psycopg.connect(ADMIN_URL, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {TEST_DB}")
    with psycopg.connect(TEST_URL) as conn:
        conn.execute(SCHEMA.read_text())
        _seed(conn)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_URL
    yield TEST_URL
    if previous is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous
    admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    admin.close()


class Audit:
    """Acces en lecture au journal d'audit de la base de test."""

    def _query(self, sql):
        with psycopg.connect(TEST_URL) as conn:
            return conn.execute(sql).fetchall()

    def count(self) -> int:
        return self._query("SELECT count(*) FROM audit_log")[0][0]

    def rows(self):
        return self._query(
            "SELECT user_id, role, tool_name, status, resume FROM audit_log ORDER BY id"
        )

    def last(self):
        return self.rows()[-1]


@pytest.fixture(autouse=True)
def audit(base_test):
    with psycopg.connect(TEST_URL) as conn:
        conn.execute("TRUNCATE audit_log RESTART IDENTITY")
    return Audit()


@pytest.fixture
def as_user(monkeypatch):
    """as_user("1") fixe MCP_USER_ID pour la suite du test ; "" simule une identite absente."""

    def _set(user_id: str):
        monkeypatch.setenv("MCP_USER_ID", user_id)

    return _set
