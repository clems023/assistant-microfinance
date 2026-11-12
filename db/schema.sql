-- Schema de l'assistant IA microfinance (donnees 100 % synthetiques).
-- Montants en francs CFA (XOF), stockes en entiers.

CREATE EXTENSION IF NOT EXISTS vector;

-- Utilisateurs de l'application et leurs roles (permissions verifiees cote serveur).
CREATE TABLE app_users (
    id          SERIAL PRIMARY KEY,
    nom         TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('agent_terrain', 'responsable', 'auditeur'))
);

CREATE TABLE clients (
    id                SERIAL PRIMARY KEY,
    nom               TEXT NOT NULL,
    telephone         TEXT NOT NULL,
    ville             TEXT NOT NULL,
    activite          TEXT NOT NULL,
    date_inscription  DATE NOT NULL
);

CREATE TABLE loans (
    id            SERIAL PRIMARY KEY,
    client_id     INTEGER NOT NULL REFERENCES clients (id),
    agent_id      INTEGER NOT NULL REFERENCES app_users (id),
    montant       INTEGER NOT NULL CHECK (montant > 0),
    taux_annuel   NUMERIC(5, 2) NOT NULL,
    duree_mois    INTEGER NOT NULL CHECK (duree_mois > 0),
    date_octroi   DATE NOT NULL,
    statut        TEXT NOT NULL CHECK (statut IN ('en_cours', 'solde', 'en_retard', 'defaut')),
    notes_agent   TEXT
);

CREATE TABLE repayments (
    id                SERIAL PRIMARY KEY,
    loan_id           INTEGER NOT NULL REFERENCES loans (id),
    echeance_numero   INTEGER NOT NULL,
    date_echeance     DATE NOT NULL,
    montant_du        INTEGER NOT NULL,
    montant_paye      INTEGER NOT NULL DEFAULT 0,
    date_paiement     DATE
);

CREATE INDEX idx_loans_client ON loans (client_id);
CREATE INDEX idx_loans_statut ON loans (statut);
CREATE INDEX idx_repayments_loan ON repayments (loan_id);

-- Journal d'audit : chaque appel d'outil de l'agent y est enregistre.
CREATE TABLE audit_log (
    id            BIGSERIAL PRIMARY KEY,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id       INTEGER REFERENCES app_users (id),
    role          TEXT NOT NULL,
    tool_name     TEXT NOT NULL,
    arguments     JSONB NOT NULL DEFAULT '{}'::jsonb,
    status        TEXT NOT NULL CHECK (status IN ('ok', 'refuse', 'erreur')),
    resume        TEXT
);

-- Documents de politique de credit pour le RAG (semaine 5).
-- La dimension du vecteur depend du modele d'embeddings retenu : a ajuster.
CREATE TABLE policy_chunks (
    id         SERIAL PRIMARY KEY,
    source     TEXT NOT NULL,
    contenu    TEXT NOT NULL,
    embedding  vector(1024)
);
