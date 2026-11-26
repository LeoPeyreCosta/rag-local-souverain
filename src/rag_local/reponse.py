"""Question → passages → réponse du modèle.

Les sources affichées viennent de la recherche, pas du modèle : un modèle de
7 milliards de paramètres numérote souvent mal ses références. Quand la
réponse n'est pas dans les passages, la consigne lui impose une phrase fixe,
que le code sait reconnaître (et l'interface afficher comme telle).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass

from .index import Index, Passage
from .ollama import Modeles

REFUS = "Je ne trouve pas cette information dans les documents."

CONSIGNE = (
    "Tu réponds aux questions des agents à partir des EXTRAITS fournis, et "
    "seulement à partir d'eux, en français, en une à trois phrases. "
    f"Si les extraits ne contiennent pas la réponse, réponds exactement : « {REFUS} » "
    "N'ajoute aucun numéro de référence."
)


def normaliser(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation, espaces simples."""
    texte = unicodedata.normalize("NFD", texte.casefold().replace("œ", "oe"))
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", texte))


#: La phrase imposée, et les tournures par lesquelles le modèle dit parfois la
#: même chose avec ses mots (« n'est pas mentionnée dans les extraits »).
_REFUS = re.compile(
    r"je ne trouve pas cette information"
    r"|\bn(?:e)? (?:sont|est) pas (?:mentionne|indique|precise|present)"
    r"|\bne (?:precise|mentionne|indique|contien|evoque)\w* pas"
    r"|\baucune information\b|\bpas d information\b"
)


def est_un_refus(reponse: str) -> bool:
    return bool(_REFUS.search(normaliser(reponse)))


def messages(question: str, passages: list[Passage]) -> list[dict[str, str]]:
    extraits = "\n\n".join(f"[{i}] (source : {p.source})\n{p.texte}" for i, p in enumerate(passages, start=1))
    return [
        {"role": "system", "content": CONSIGNE},
        {"role": "user", "content": f"EXTRAITS :\n{extraits}\n\nQUESTION : {question}"},
    ]


@dataclass
class Recherche:
    question: str
    passages: list[tuple[float, Passage]]


def rechercher(question: str, index: Index, modeles: Modeles, nombre: int = 4) -> Recherche:
    if index.modele_embeddings != modeles.modele_embeddings:
        raise ValueError(
            f"L'index a été construit avec {index.modele_embeddings} et la question serait "
            f"vectorisée avec {modeles.modele_embeddings} : réindexez."
        )
    vecteur = modeles.vecteurs([question])[0]
    return Recherche(question, index.rechercher(vecteur, nombre))


def repondre(recherche: Recherche, modeles: Modeles) -> Iterator[str]:
    """La réponse, morceau par morceau."""
    if not recherche.passages:
        yield REFUS
        return
    yield from modeles.repondre(messages(recherche.question, [p for _, p in recherche.passages]))
