"""Evals : structure de cases.json et logique de comparaison (sans LLM ni base de dev)."""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))
import run_evals  # noqa: E402

OUTILS = {"rechercher_client", "statut_pret", "prets_en_retard", "journal_audit"}


def test_cases_structure():
    cas = run_evals.charger_cas()
    assert len(cas) == 10
    assert len({c["id"] for c in cas}) == 10
    assert Counter(c["categorie"] for c in cas) == {
        "simple": 4, "sans_resultat": 2, "hors_perimetre": 2, "ambigue": 2,
    }
    for c in cas:
        assert {"id", "question", "outil_attendu", "reponse_attendue", "sql"} <= c.keys()
        assert c["outil_attendu"] is None or c["outil_attendu"] in OUTILS


def test_evaluer_reussite_ignore_casse_accents_espaces():
    cas = {"outil_attendu": "statut_pret"}
    valeurs = {"montant": 1515000, "statut": "en retard", "_garde": 1}
    reponse = "Le prêt est EN RETARD : 1 515 000 XOF."
    assert run_evals.evaluer(cas, valeurs, ["statut_pret"], reponse) == []


def test_evaluer_mauvais_outil_et_valeur_absente():
    cas = {"outil_attendu": "statut_pret"}
    echecs = run_evals.evaluer(cas, {"montant": 42}, ["prets_en_retard"], "rien")
    assert len(echecs) == 2


def test_evaluer_hors_perimetre_exige_aucun_outil_et_mot_cle():
    cas = {"outil_attendu": None, "mots_cles": ["ne peux pas"]}
    assert run_evals.evaluer(cas, {}, [], "Je ne peux pas supprimer.") == []
    assert len(run_evals.evaluer(cas, {}, ["statut_pret"], "Fait.")) == 2
