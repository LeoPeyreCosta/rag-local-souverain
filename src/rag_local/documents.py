"""Lecture des documents et découpage en passages."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

EXTENSIONS = (".txt", ".md", ".pdf")


def lire_fichier(chemin: Path) -> str:
    """Texte d'un fichier .txt, .md ou .pdf (vide pour les autres formats)."""
    extension = chemin.suffix.lower()
    if extension in (".txt", ".md"):
        return chemin.read_text(encoding="utf-8", errors="ignore")
    if extension == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(chemin).pages)
    return ""


def lire_documents(dossier: Path) -> list[tuple[str, str]]:
    """(chemin relatif, texte) de chaque document lisible du dossier."""
    documents = []
    for chemin in sorted(Path(dossier).rglob("*")):
        if chemin.is_file() and chemin.suffix.lower() in EXTENSIONS:
            texte = lire_fichier(chemin)
            if texte.strip():
                documents.append((chemin.relative_to(dossier).as_posix(), texte))
    return documents


def empreinte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def decouper(texte: str, taille: int = 500, chevauchement: int = 80) -> list[str]:
    """Passages d'environ ``taille`` caractères qui se chevauchent, coupés de
    préférence à une fin de ligne, sinon entre deux mots."""
    texte = re.sub(r"[ \t]+", " ", texte).strip()
    morceaux: list[str] = []
    debut, longueur = 0, len(texte)
    while debut < longueur:
        fin = min(debut + taille, longueur)
        coupe = texte.rfind("\n", debut + int(taille * 0.6), fin)
        if coupe == -1:
            coupe = texte.rfind(" ", debut + int(taille * 0.6), fin)
        if coupe == -1 or fin == longueur:
            coupe = fin
        bloc = texte[debut:coupe].strip()
        if bloc:
            morceaux.append(bloc)
        if coupe >= longueur:
            break
        debut = max(coupe - chevauchement, debut + 1)
        espace = texte.find(" ", debut)  # recommencer au début d'un mot
        if espace != -1 and espace < coupe:
            debut = espace + 1
    return morceaux
