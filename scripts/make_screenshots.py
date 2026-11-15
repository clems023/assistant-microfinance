"""Genere les captures d'ecran (docs/images/) a partir des VRAIES sorties des commandes.

Chaque commande est executee, sa sortie est rendue telle quelle dans une image de type terminal
(le texte n'est jamais retape ni modifie ; seules des couleurs sont appliquees).
Prerequis : docker compose up -d, python data/generate.py, pip install -r requirements-dev.txt.

Usage : python scripts/make_screenshots.py
Produit : docs/images/demo-roles.png (1200x1200) et docs/images/audit-log.png (1200x627).
La police est agrandie au maximum pour que le texte remplisse l'image, puis le bloc est centré.
Chaque execution relance la demo, qui ajoute des lignes dans audit_log de la base de dev.
"""

import re
import subprocess
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "docs" / "images"
TITRE = "assistant-microfinance"

# Colonnes de la demo : volontairement etroites pour rester lisibles sur telephone.
DEMO = ["scripts/demo_roles.py", "--largeur", "32", "--max-lignes", "4"]
SQL_AUDIT = (
    "SELECT to_char(occurred_at, 'HH24:MI:SS') AS heure, role, tool_name, status, arguments"
    " FROM audit_log ORDER BY id DESC LIMIT 8"
)
AUDIT = ["docker", "exec", "microfinance-db", "psql", "-U", "microfinance", "-c", SQL_AUDIT]

POLICES = [
    ("/System/Library/Fonts/Menlo.ttc", 0),
    ("/System/Library/Fonts/Monaco.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 0),
    ("/Library/Fonts/Courier New.ttf", 0),
]
ECHELLE = 2  # rendu en 2x puis reduction : bords et texte plus lisses
INTERLIGNE = 1.4

COULEURS = {
    "fond_haut": (27, 35, 64), "fond_bas": (11, 16, 32), "fenetre": (20, 23, 31),
    "barre": (30, 34, 44), "texte": (215, 218, 224), "doux": (107, 114, 128),
    "invite": (126, 231, 135), "titre_col": (121, 192, 255), "refus": (255, 123, 114),
    "ok": (126, 231, 135),
}


def police(taille: int) -> ImageFont.FreeTypeFont:
    for chemin, index in POLICES:
        if Path(chemin).exists():
            return ImageFont.truetype(chemin, taille, index=index)
    sys.exit("Aucune police monospace trouvee : ajouter un chemin dans POLICES.")


def verifier_glyphes(f: ImageFont.FreeTypeFont, lignes: list[str]):
    """Echoue si un caractere du texte n'existe pas dans la police (il serait affiche en carre)."""
    absent = f.getmask("\U0010FFFF")  # glyphe .notdef de la police
    manquants = sorted({
        c for ligne in lignes for c in ligne
        if c != " " and bytes(f.getmask(c)) == bytes(absent) and f.getmask(c).size == absent.size
    })
    if manquants:
        sys.exit(f"Caracteres absents de la police : {manquants}")


def executer(commande: list[str]) -> str:
    """Execute la commande et retourne sa sortie standard, sans la modifier."""
    resultat = subprocess.run(commande, cwd=RACINE, capture_output=True, text=True)
    if resultat.returncode != 0:
        sys.exit(f"Echec de {' '.join(commande[:3])} ...\n{resultat.stderr}")
    return resultat.stdout.rstrip("\n")


def invite(commande: list[str], largeur: int) -> list[str]:
    """Ligne(s) de prompt : la commande reellement lancee (python/docker), repliee en largeur."""
    affichee = ["python" if c == sys.executable else c for c in commande]
    texte = "$ " + " ".join(f'"{c}"' if " " in c else c for c in affichee)
    lignes = textwrap.wrap(texte, largeur - 2, subsequent_indent="    ", break_long_words=False)
    return [l + " \\" if i < len(lignes) - 1 else l for i, l in enumerate(lignes)]


def segments(ligne: str, est_invite: bool):
    """Decoupe une ligne en (texte, couleur) : coloration seulement, texte inchange."""
    if est_invite:
        return [(ligne, COULEURS["invite"])]
    if re.fullmatch(r"[-+]+", ligne.strip()) or re.fullmatch(r"\(\d+ rows?\)", ligne.strip()):
        return [(ligne, COULEURS["doux"])]
    if ligne.startswith(("agent_terrain (id", "Question", "DÉMO")):
        return [(ligne, COULEURS["titre_col"])]
    morceaux, couleur_par_mot = [], {"refuse": "refus", "erreur": "refus", "ok": "ok",
                                     "Prêt introuvable.": "refus"}
    for partie in re.split(r"(\brefuse\b|\berreur\b|\bok\b|Prêt introuvable\.)", ligne):
        cle = couleur_par_mot.get(partie, "texte")
        morceaux.append((partie, COULEURS[cle]))
    return morceaux


def fond_degrade(largeur: int, hauteur: int) -> Image.Image:
    img = Image.new("RGB", (largeur, hauteur))
    d = ImageDraw.Draw(img)
    for y in range(hauteur):
        t = y / max(hauteur - 1, 1)
        d.line([(0, y), (largeur, y)], fill=tuple(
            int(COULEURS["fond_haut"][i] * (1 - t) + COULEURS["fond_bas"][i] * t) for i in range(3)))
    return img


def rendre(lignes: list[str], nb_invite: int, largeur: int, hauteur: int, chemin: Path):
    marge, pad, barre = 28 * ECHELLE, 22 * ECHELLE, 64 * ECHELLE
    W, H = largeur * ECHELLE, hauteur * ECHELLE
    interieur_l = W - 2 * marge - 2 * pad
    interieur_h = H - 2 * marge - barre - 2 * pad

    # Plus grande police dont le texte tient dans la fenetre.
    plus_long = max(len(l) for l in lignes)
    taille = 36 * ECHELLE
    while taille > 16 * ECHELLE:
        f = police(taille)
        if (f.getlength("0") * plus_long <= interieur_l
                and len(lignes) * int(taille * INTERLIGNE) <= interieur_h):
            break
        taille -= 1
    else:
        sys.exit(f"Le texte ne tient pas dans {largeur}x{hauteur} avec une police lisible.")
    f = police(taille)
    verifier_glyphes(f, lignes)
    pas = int(taille * INTERLIGNE)
    largeur_bloc = int(f.getlength("0") * plus_long)
    hauteur_bloc = len(lignes) * pas
    print(f"{chemin.name} : police {taille / ECHELLE:.1f}px, {len(lignes)} lignes, "
          f"{plus_long} caracteres max, remplissage {largeur_bloc / interieur_l:.0%} x "
          f"{hauteur_bloc / interieur_h:.0%}")

    img = fond_degrade(W, H)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([marge, marge, W - marge, H - marge], radius=22 * ECHELLE,
                        fill=COULEURS["fenetre"])
    # Barre de titre : bords hauts arrondis, boutons et titre centre.
    d.rounded_rectangle([marge, marge, W - marge, marge + barre], radius=22 * ECHELLE,
                        fill=COULEURS["barre"], corners=(True, True, False, False))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx, cy, r = marge + (30 + i * 30) * ECHELLE, marge + barre // 2, 8 * ECHELLE
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    ft = police(22 * ECHELLE)
    d.text((W // 2, marge + barre // 2), TITRE, font=ft, fill=COULEURS["doux"], anchor="mm")

    # Bloc centre dans la zone de texte : marges equilibrees en haut/bas et a gauche/droite.
    x0 = marge + pad + (interieur_l - largeur_bloc) // 2
    y0 = marge + barre + pad + (interieur_h - hauteur_bloc) // 2
    for n, ligne in enumerate(lignes):
        x = x0
        for texte, couleur in segments(ligne, n < nb_invite):
            d.text((x, y0 + n * pas), texte, font=f, fill=couleur)
            x += f.getlength(texte)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    img.resize((largeur, hauteur), Image.LANCZOS).save(chemin, optimize=True)


def main():
    # 1. Demo des roles : les deux colonnes de la vraie sortie du script.
    commande = [sys.executable, *DEMO]
    sortie = executer(commande)
    entete = invite(commande, 75)
    rendre(entete + [""] + sortie.splitlines(), len(entete), 1200, 1200, SORTIE / "demo-roles.png")

    # 2. Journal d'audit : derniers appels, apres la demo (refus compris).
    sortie = executer(AUDIT)
    entete = invite(AUDIT, 70)
    rendre(entete + [""] + sortie.splitlines(), len(entete), 1200, 627, SORTIE / "audit-log.png")


if __name__ == "__main__":
    main()
