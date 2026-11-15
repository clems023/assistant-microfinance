"""Genere un jeu de donnees synthetique de microfinance dans PostgreSQL.

Usage :
    python data/generate.py              # insere dans la base
    python data/generate.py --dry-run    # genere et affiche les comptes, sans base
    python data/generate.py --seed 7 --clients 300

Chaque pret porte une note d'agent fictive ; 5 cas atypiques sont ajoutes volontairement.
Toutes les donnees sont fictives. Ne jamais y mettre de donnees reelles.
"""

import argparse
import os
import random
from datetime import date, timedelta

DEFAULT_URL = "postgresql://microfinance:microfinance@localhost:5433/microfinance"

VILLES = ["Lomé", "Kpalimé", "Atakpamé", "Sokodé", "Kara", "Dapaong", "Tsévié", "Aného"]
ACTIVITES = ["commerce", "agriculture", "couture", "transport", "restauration", "artisanat"]
# Noms fictifs, ecrits en dur (aucune donnee reelle). Origines melangees : ewe, mina, kabiye,
# tem, plus des prenoms usuels au Togo. Aucun nom de personnalite publique volontairement.
PRENOMS_F = [
    "Afi", "Ama", "Akossiwa", "Adjoa", "Abla", "Yawa", "Dzifa", "Mawuena", "Kafui", "Eyram",
    "Delali", "Akouavi", "Ablavi", "Essi", "Kokoé", "Esther", "Grâce", "Prisca", "Judith",
    "Nadège", "Chantal", "Edwige", "Ornella", "Estelle", "Honorine", "Rahamatou", "Safiatou",
    "Rabiatou", "Zeinabou", "Fatoumata",
]
PRENOMS_M = [
    "Kodjo", "Komla", "Kokou", "Koffi", "Kossi", "Yao", "Mawuli", "Selom", "Elom", "Senam",
    "Edem", "Mawuko", "Komi", "Yawovi", "Ayité", "Kwami", "Essohanam", "Essozimna", "Essowè",
    "Issifou", "Moussa", "Yacoubou", "Idrissou", "Bouraima", "Alidou", "Abdoul", "Ibrahim",
    "Emmanuel", "Patrice", "Désiré",
]
NOMS = [
    "Agbodjan", "Akakpo", "Amegah", "Amouzou", "Adjakly", "Agbeko", "Atsou", "Attiogbe",
    "Hounkpati", "Kpodar", "Mensah", "Noumonvi", "Sossou", "Tomety", "Koudjo", "Ayivi", "Folly",
    "Djossou", "Agbadji", "Aguigah", "Zogbo", "Ayena", "Kuevi", "Lawson", "Quashie", "Pyalo",
    "Lamboni", "Tchagnao", "Kassegne", "Awesso", "Bidamon", "Kolani", "Mouzou", "Walla",
    "Alassani", "Salifou", "Ouro-Gnaou", "Tchakpélé", "Abalo", "Kondo",
]

# Personnel de l'agence : roles et ids inchanges (1-2 agents terrain, 3 responsable, 4 auditeur).
USERS = [
    ("Kossi Amegah", "agent_terrain"),
    ("Afi Tomety", "agent_terrain"),
    ("Adjoa Lawson", "responsable"),
    ("Issifou Kassegne", "auditeur"),
]

# Notes d'agent fictives, courtes, selon la situation du pret.
NOTES = {
    "solde": [
        "Pret rembourse sans incident.",
        "Client ponctuel, bon candidat pour un renouvellement.",
        "Solde en avance sur le calendrier, relation de confiance.",
        "Remboursement complet, activite en croissance.",
    ],
    "en_cours": [
        "Visite de suivi faite, activite stable.",
        "Paie regulierement, rien a signaler.",
        "Client satisfait, demande un second pret plus tard.",
        "Stock renouvele recemment, bonne dynamique de vente.",
    ],
    "en_retard": [
        "Retard signale, client joint par telephone, promet de regulariser.",
        "Baisse de revenus saisonniere, a surveiller de pres.",
        "Absent lors de la derniere visite, relance prevue.",
        "Paiements decales depuis plusieurs semaines.",
    ],
    "defaut": [
        "Plus de paiement depuis des mois, client injoignable.",
        "Activite arretee, dossier a transmettre au responsable.",
        "Garant contacte sans resultat, defaut probable.",
        "Difficultes familiales invoquees, aucun remboursement recu.",
    ],
}


def add_months(d: date, months: int) -> date:
    """Ajoute des mois a une date en bornant le jour a 28."""
    total = d.month - 1 + months
    return date(d.year + total // 12, total % 12 + 1, min(d.day, 28))


def nom_fictif(rng_noms: random.Random) -> str:
    """Prenom + nom togolais fictifs ; le prenom suit le genre tire (pas de champ genre en base)."""
    prenoms = PRENOMS_F if rng_noms.random() < 0.5 else PRENOMS_M
    return f"{rng_noms.choice(prenoms)} {rng_noms.choice(NOMS)}"


def make_clients(rng_noms: random.Random, rng: random.Random, n: int, today: date):
    rows = []
    for _ in range(n):
        telephone = "+228 9%d %02d %02d %02d" % (
            rng.randint(0, 9), rng.randint(0, 99), rng.randint(0, 99), rng.randint(0, 99),
        )
        inscription = today - timedelta(days=rng.randint(60, 900))
        rows.append((nom_fictif(rng_noms), telephone, rng.choice(VILLES), rng.choice(ACTIVITES), inscription))
    return rows


def make_loan(rng: random.Random, client_id: int, agent_ids: list, inscription: date, today: date,
              *, montant=None, duree=None, octroi=None, profil=None, notes=None):
    """Retourne (pret, echeances). Le statut est deduit des paiements simules.

    Les parametres nommes servent aux cas atypiques ; sinon tout est tire au hasard.
    """
    if montant is None:
        montant = rng.randrange(50_000, 2_000_001, 5_000)
    taux = round(rng.uniform(18.0, 24.0), 2)
    if duree is None:
        duree = rng.choice([3, 6, 9, 12])
    if octroi is None:
        latest_start = today - timedelta(days=30)
        earliest_start = min(inscription + timedelta(days=7), latest_start)
        span = max((latest_start - earliest_start).days, 1)
        octroi = earliest_start + timedelta(days=rng.randint(0, span))

    total_du = montant * (1 + taux / 100 * duree / 12)
    mensualite = int(round(total_du / duree, -1))

    # Profil de payeur : la plupart paient a l'heure, certains en retard, quelques defauts.
    if profil is None:
        profil = rng.choices(["bon", "retard", "defaut"], weights=[78, 15, 7])[0]
    echeances = []
    for numero in range(1, duree + 1):
        date_ech = add_months(octroi, numero)
        paye, date_paiement = 0, None
        if date_ech <= today:
            if profil == "bon":
                paye, date_paiement = mensualite, date_ech + timedelta(days=rng.randint(-3, 3))
            elif profil == "retard":
                # Paie en retard, et rate la derniere echeance echue.
                if date_ech + timedelta(days=45) <= today:
                    paye, date_paiement = mensualite, date_ech + timedelta(days=rng.randint(5, 40))
            else:  # defaut : cesse de payer apres la 2e echeance
                if numero <= 2:
                    paye, date_paiement = mensualite, date_ech + timedelta(days=rng.randint(0, 10))
            if date_paiement and date_paiement > today:
                date_paiement = today
        echeances.append((numero, date_ech, mensualite, paye, date_paiement))

    impayes = [e for e in echeances if e[1] <= today and e[3] < e[2]]
    if not impayes and all(e[1] <= today for e in echeances):
        statut = "solde"
    elif not impayes:
        statut = "en_cours"
    else:
        plus_ancien = min(e[1] for e in impayes)
        statut = "defaut" if (today - plus_ancien).days > 90 else "en_retard"

    if notes is None:
        notes = rng.choice(NOTES[statut])
    pret = (client_id, rng.choice(agent_ids), montant, taux, duree, octroi, statut, notes)
    return pret, echeances


def atypical_cases(today: date):
    """5 cas volontairement atypiques : (libelle, [parametres de make_loan, ...]).

    Les dates sont relatives a `today` pour que les statuts restent coherents.
    """
    ago = lambda days: today - timedelta(days=days)
    return [
        ("3 prets en cours pour un meme client", [
            dict(montant=300_000, duree=6, octroi=ago(70), profil="bon",
                 notes="Troisieme pret ouvert en quelques semaines, cumul a surveiller."),
            dict(montant=450_000, duree=9, octroi=ago(45), profil="bon",
                 notes="Deuxieme pret accorde avant la fin du premier."),
            dict(montant=250_000, duree=12, octroi=ago(20), profil="bon",
                 notes="Nouvelle demande acceptee, endettement total eleve."),
        ]),
        ("montant tres eleve (12 000 000 XOF)", [
            dict(montant=12_000_000, duree=12, octroi=ago(120), profil="bon",
                 notes="Montant exceptionnel, validation du responsable obtenue."),
        ]),
        ("retards repetes sur presque toutes les echeances", [
            dict(montant=900_000, duree=12, octroi=add_months(ago(20), -10), profil="retard",
                 notes="Paie systematiquement en retard, relances hebdomadaires."),
        ]),
        ("defaut sur un gros montant", [
            dict(montant=6_000_000, duree=12, octroi=ago(240), profil="defaut",
                 notes="Defaut apres deux echeances, garantie a verifier."),
        ]),
        ("ancien defaut puis nouveau pret", [
            dict(montant=400_000, duree=9, octroi=ago(300), profil="defaut",
                 notes="Defaut non regularise, dossier ouvert."),
            dict(montant=1_200_000, duree=12, octroi=ago(15), profil="bon",
                 notes="Nouveau pret accorde malgre un defaut ancien, a revoir."),
        ]),
    ]


def generate(seed: int, n_clients: int, today: date):
    rng = random.Random(seed)
    # Flux separe, derive de la meme graine : les noms ne decalent pas les autres tirages
    # (villes, activites, montants...), qui restent identiques pour un seed donne.
    rng_noms = random.Random(f"noms-{seed}")

    clients = make_clients(rng_noms, rng, n_clients, today)
    agent_ids = [i + 1 for i, (_, role) in enumerate(USERS) if role == "agent_terrain"]

    loans, repayments = [], []

    def add(client_id, client, **overrides):
        pret, echeances = make_loan(rng, client_id, agent_ids, client[4], today, **overrides)
        loans.append(pret)
        repayments.extend((len(loans), *e) for e in echeances)

    for client_id, client in enumerate(clients, start=1):
        for _ in range(rng.choice([0, 1, 1, 1, 2])):
            add(client_id, client)

    # Cas atypiques : un client dedie chacun, ajoutes apres les clients aleatoires.
    atypiques = []
    for libelle, loan_specs in atypical_cases(today):
        client = make_clients(rng_noms, rng, 1, today)[0]
        clients.append(client)
        client_id = len(clients)
        # Inscription anterieure a tous les prets du scenario.
        clients[-1] = (*client[:4], today - timedelta(days=900))
        for spec in loan_specs:
            add(client_id, clients[-1], **spec)
        atypiques.append((libelle, client_id, clients[-1][0]))
    return clients, loans, repayments, atypiques


def insert(url: str, clients, loans, repayments):
    import psycopg

    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "TRUNCATE repayments, loans, clients, audit_log, app_users RESTART IDENTITY CASCADE"
        )
        cur.executemany("INSERT INTO app_users (nom, role) VALUES (%s, %s)", USERS)
        cur.executemany(
            "INSERT INTO clients (nom, telephone, ville, activite, date_inscription)"
            " VALUES (%s, %s, %s, %s, %s)",
            clients,
        )
        cur.executemany(
            "INSERT INTO loans (client_id, agent_id, montant, taux_annuel, duree_mois,"
            " date_octroi, statut, notes_agent) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            loans,
        )
        cur.executemany(
            "INSERT INTO repayments (loan_id, echeance_numero, date_echeance, montant_du,"
            " montant_paye, date_paiement) VALUES (%s, %s, %s, %s, %s, %s)",
            repayments,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--clients", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    today = date.today()
    clients, loans, repayments, atypiques = generate(args.seed, args.clients, today)

    statuts = {}
    for loan in loans:
        statuts[loan[6]] = statuts.get(loan[6], 0) + 1
    print(f"{len(clients)} clients, {len(loans)} prets, {len(repayments)} echeances")
    print("Statuts des prets :", statuts)
    print("Cas atypiques (clients ajoutes en fin de liste) :")
    for libelle, client_id, nom in atypiques:
        prets = [(i + 1, l) for i, l in enumerate(loans) if l[0] == client_id]
        detail = ", ".join(f"pret {i}: {l[2]:,} XOF {l[6]}".replace(",", " ") for i, l in prets)
        print(f"  - {libelle} -> client {client_id} ({nom}) | {detail}")
    print("Exemple de notes_agent :", [l[7] for l in loans[:3]])

    if args.dry_run:
        return
    insert(os.environ.get("DATABASE_URL", DEFAULT_URL), clients, loans, repayments)
    print("Donnees inserees.")


if __name__ == "__main__":
    main()
