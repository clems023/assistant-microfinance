"""Permissions par role du serveur MCP (base de test fictive, voir conftest.py)."""

import pytest

import server
from conftest import AGENT_1, AGENT_2, AUDITEUR, NOTE_SECRETE, RESPONSABLE, TELEPHONE

INTROUVABLE = "Prêt introuvable."


def sans_fuite(texte: str):
    assert NOTE_SECRETE not in texte
    assert TELEPHONE not in texte


# 1. Utilisateur inconnu
@pytest.mark.parametrize("identite", ["999", "", "abc"])
def test_utilisateur_inconnu_refuse(as_user, audit, identite):
    as_user(identite)
    sorties = [
        server.rechercher_client("Alpha"),
        server.statut_pret(1),
        server.prets_en_retard(),
    ]
    assert all(s.startswith("Accès refusé") for s in sorties)
    lignes = audit.rows()
    assert len(lignes) == 3
    assert all(role == "inconnu" and status == "refuse" for _, role, _, status, _ in lignes)


# 2. agent_terrain bloque sur le pret d'un autre
def test_agent_bloque_sur_pret_d_un_autre(as_user, audit):
    as_user(AGENT_1)
    pret_autre_agent = server.statut_pret(2)  # existe, mais appartient a l'agent 2
    pret_inexistant = server.statut_pret(99999)
    assert pret_autre_agent == INTROUVABLE
    assert pret_autre_agent == pret_inexistant  # exactement le meme message
    (_, _, _, status_autre, _), (_, _, _, status_inexistant, _) = audit.rows()
    assert status_autre == "refuse"  # la tentative est journalisee
    assert status_inexistant == "ok"


# 3. agent_terrain voit ses propres prets
def test_agent_voit_ses_prets(as_user):
    as_user(AGENT_1)
    pret = server.statut_pret(1)
    assert "Prêt #1" in pret and "500 000 XOF" in pret
    assert "1 payée(s), 2 restante(s)" in pret

    clients = server.rechercher_client("Alpha")
    assert "Awa Alpha" in clients
    assert "SansPret" not in clients  # client sans pret de cet agent
    assert server.rechercher_client("Kofi") == "Aucun client trouvé."  # client de l'agent 2

    retards = server.prets_en_retard()
    assert "1 prêt(s) en retard" in retards  # seulement le pret 3
    assert "#3 " in retards and "#2 " not in retards
    for s in (pret, clients, retards):
        sans_fuite(s)


# 3 bis. Symetrie : l'agent 2 est lui aussi cloisonne
def test_agent_2_ne_voit_que_son_portefeuille(as_user):
    as_user(AGENT_2)
    retards = server.prets_en_retard()
    assert "1 prêt(s) en retard" in retards
    assert "#2 " in retards and "#1 " not in retards and "#3 " not in retards

    # Clients de l'agent 1 introuvables, client de l'agent 2 trouve.
    assert server.rechercher_client("Awa") == "Aucun client trouvé."
    assert server.rechercher_client("Esi") == "Aucun client trouvé."
    assert "Kofi Beta" in server.rechercher_client("Kofi")

    # Prets de l'agent 1 : meme message que pour un pret inexistant.
    assert server.statut_pret(1) == INTROUVABLE
    assert server.statut_pret(3) == INTROUVABLE
    assert "Prêt #2" in server.statut_pret(2)


# Les statuts stockes (en_retard, defaut) sont affiches avec des libelles accentues.
def test_statuts_affiches_avec_accents(as_user):
    as_user(RESPONSABLE)
    for texte in (server.statut_pret(2), server.statut_pret(3), server.prets_en_retard()):
        assert "en_retard" not in texte and "defaut" not in texte
    assert "en retard" in server.statut_pret(2)
    assert "défaut" in server.statut_pret(3)
    assert "en cours" in server.statut_pret(1)
    assert "impayé" in server.prets_en_retard()


# 4. responsable (et auditeur en lecture) voient tout
@pytest.mark.parametrize("utilisateur", [RESPONSABLE, AUDITEUR])
def test_acces_complet_en_lecture(as_user, utilisateur):
    as_user(utilisateur)
    for loan_id in (1, 2, 3):
        assert f"Prêt #{loan_id}" in server.statut_pret(loan_id)
    clients = server.rechercher_client("Alpha")
    assert "Awa Alpha" in clients and "Ama Alpha SansPret" in clients
    assert "Kofi Beta" in server.rechercher_client("Kofi")
    retards = server.prets_en_retard()
    assert "2 prêt(s) en retard" in retards and "#2 " in retards and "#3 " in retards
    sans_fuite(clients + retards)


# 5. Seul l'auditeur peut appeler journal_audit
@pytest.mark.parametrize("utilisateur", [AGENT_1, AGENT_2, RESPONSABLE, "999"])
def test_journal_audit_refuse_hors_auditeur(as_user, audit, utilisateur):
    as_user(utilisateur)
    texte = server.journal_audit(5)
    assert texte.startswith("Accès refusé")
    assert audit.last()[3] == "refuse"


def test_message_de_refus_generique(as_user):
    """Le refus ne nomme aucun role : il reste vrai si la matrice PERMISSIONS change."""
    as_user(AGENT_1)
    assert server.journal_audit(5) == "Accès refusé : rôle non autorisé pour cet outil."


def test_journal_audit_pour_auditeur(as_user, audit):
    as_user(AGENT_1)
    server.statut_pret(2)  # une tentative refusee a retrouver dans le journal
    as_user(AUDITEUR)
    texte = server.journal_audit(5)
    assert not texte.startswith("Accès refusé")
    assert "statut_pret" in texte and "refuse" in texte
    assert audit.last()[2:4] == ("journal_audit", "ok")
    assert len(server.journal_audit(2).splitlines()) <= 2
    assert len(server.journal_audit(1000).splitlines()) <= 50  # plafond
    sans_fuite(texte)


# 6. Chaque appel cree exactement une ligne dans audit_log
APPELS = [
    ("ok", lambda: server.rechercher_client("Alpha")),
    ("ok", lambda: server.statut_pret(1)),
    ("ok", lambda: server.prets_en_retard()),
    ("ok", lambda: server.statut_pret(99999)),
    ("refuse", lambda: server.statut_pret(2)),  # hors portefeuille (agent 1)
    ("refuse", lambda: server.journal_audit(5)),  # role non autorise
    ("erreur", lambda: server.statut_pret("abc")),  # erreur SQL
    ("erreur", lambda: server.rechercher_client("a")),  # nom trop court
]


@pytest.mark.parametrize("attendu, appel", APPELS)
def test_un_appel_une_ligne_d_audit(as_user, audit, attendu, appel):
    as_user(AGENT_1)
    avant = audit.count()
    appel()
    assert audit.count() == avant + 1
    assert audit.last()[3] == attendu


# Base injoignable : message clair au lieu d'une exception brute
def test_base_injoignable_message_clair(as_user, monkeypatch):
    as_user(RESPONSABLE)
    monkeypatch.setenv("DATABASE_URL", "postgresql://microfinance:faux@localhost:1/microfinance")
    sorties = [server.rechercher_client("Alpha"), server.statut_pret(1), server.prets_en_retard()]
    assert all(s.startswith("Base de données injoignable") for s in sorties)
