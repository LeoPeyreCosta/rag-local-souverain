"""Question → passages → réponse du modèle → phrase qui l'appuie.

Les sources affichées viennent de la recherche, pas du modèle : un modèle de
7 milliards de paramètres numérote souvent mal ses références. Quand la
réponse n'est pas dans les passages, la consigne lui impose une phrase fixe,
que le code sait reconnaître (et l'interface afficher comme telle).

Une fois la réponse écrite, le modèle doit recopier la phrase des passages
qui la justifie. Le code cherche cette citation dans les passages, à
quelques mots près : retrouvée, elle est surlignée pour que l'agent vérifie
la réponse d'un coup d'œil ; introuvable ou absente, la réponse est
signalée comme non appuyée. Une citation retrouvée prouve que la phrase
existe, pas que la réponse en découle.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from difflib import SequenceMatcher

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
    r"|\bn(?:e)? (?:sont|est) pas (?:mentionne|indique|precise|specifie|present)"
    r"|\bne (?:precise|specifie|mentionne|indique|contien|evoque)\w* pas"
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


# ------------------------------------------------------------------ appui
#: Posée à la suite de la réponse, dans le même échange : Ollama réutilise
#: alors les extraits déjà lus au lieu de les relire.
CONSIGNE_APPUI = (
    "Recopie mot pour mot, sans rien reformuler, la phrase des extraits qui justifie ta réponse, "
    "sans le numéro ni la source de l'extrait. "
    "Si aucune phrase des extraits ne la justifie, renvoie une citation vide."
)
#: Ce que le modèle recopie parfois de l'en-tête de l'extrait : « [1] (source : conges.md) ».
_EN_TETE = re.compile(r"^\s*(?:\[\d+\]\s*)?(?:\(source\s*:[^)]*\)\s*)?")
SCHEMA_APPUI = {
    "type": "object",
    "properties": {"citation": {"type": "string"}},
    "required": ["citation"],
}
#: Ressemblance minimale (0 à 1) entre la citation et un morceau de passage :
#: le modèle recopie rarement à la lettre (ponctuation, article oublié).
SEUIL_APPUI = 0.8
#: En dessous, une citation (« deux jours ») se retrouverait n'importe où.
MOTS_MIN_APPUI = 4


@dataclass
class Appui:
    """Morceau d'un passage qui appuie la réponse."""

    rang: int  # 1 pour le passage le plus proche de la question
    debut: int  # position dans le texte du passage, en caractères
    fin: int
    ressemblance: float


def _mots(texte: str) -> list[tuple[str, int, int]]:
    """Mots normalisés du texte, avec leur position dans le texte d'origine."""
    mots = []
    for trouve in re.finditer(r"[^\W_]+", texte):
        for mot in normaliser(trouve.group()).split():
            mots.append((mot, trouve.start(), trouve.end()))
    return mots


#: Fin de phrase dans une citation.
_FIN_DE_PHRASE = re.compile(r"(?<=[.!?;])\s+")


def localiser(citation: str, passages: list[Passage]) -> Appui | None:
    """Le morceau de passage qui correspond à la citation, ou None.

    La citation est d'abord cherchée d'un seul tenant. Le modèle assemble
    parfois des phrases non contiguës d'un même passage (la première et la
    troisième) : chaque phrase est alors cherchée à part, et si toutes se
    retrouvent dans le même passage, on retient le morceau qui va de la
    première à la dernière."""
    citation = _EN_TETE.sub("", citation, count=1)
    entiere = _chercher(normaliser(citation).split(), passages)
    if entiere:
        return entiere
    phrases = [normaliser(p).split() for p in _FIN_DE_PHRASE.split(citation)]
    phrases = [p for p in phrases if len(p) >= MOTS_MIN_APPUI]
    if len(phrases) < 2:
        return None
    trouvees = [_chercher(p, passages) for p in phrases]
    if any(t is None for t in trouvees):
        return None
    morceaux = [t for t in trouvees if t]
    if len({t.rang for t in morceaux}) > 1:
        return None
    return Appui(
        morceaux[0].rang,
        min(t.debut for t in morceaux),
        max(t.fin for t in morceaux),
        min(t.ressemblance for t in morceaux),
    )


def _chercher(cible: list[str], passages: list[Passage]) -> Appui | None:
    """La fenêtre de passage la plus proche de la suite de mots, si elle l'est
    assez. On compare la citation à chaque fenêtre de longueur voisine de
    chaque passage : quelques milliers de comparaisons pour 4 passages de
    500 caractères, quelques millisecondes."""
    n = len(cible)
    if n < MOTS_MIN_APPUI:
        return None
    comparateur = SequenceMatcher(None, autojunk=False)
    comparateur.set_seq2(cible)
    meilleur: Appui | None = None
    score_max = 0.0
    for rang, passage in enumerate(passages, start=1):
        mots = _mots(passage.texte)
        suite = [m for m, _, _ in mots]
        for debut in range(len(suite)):
            for taille in range(max(1, n - 3), min(n + 3, len(suite) - debut) + 1):
                comparateur.set_seq1(suite[debut : debut + taille])
                if comparateur.real_quick_ratio() <= score_max or comparateur.quick_ratio() <= score_max:
                    continue
                score = comparateur.ratio()
                if score > score_max:
                    score_max = score
                    meilleur = Appui(rang, mots[debut][1], mots[debut + taille - 1][2], score)
    return meilleur if meilleur and meilleur.ressemblance >= SEUIL_APPUI else None


def demander_citation(recherche: Recherche, reponse: str, modeles: Modeles) -> str:
    """La phrase des passages que le modèle donne pour justifier sa réponse."""
    echanges = messages(recherche.question, [p for _, p in recherche.passages]) + [
        {"role": "assistant", "content": reponse},
        {"role": "user", "content": CONSIGNE_APPUI},
    ]
    try:
        citation = json.loads(modeles.repondre_json(echanges, SCHEMA_APPUI)).get("citation", "")
    except (ValueError, AttributeError):
        return ""
    return citation if isinstance(citation, str) else ""


def appuyer(recherche: Recherche, reponse: str, modeles: Modeles) -> tuple[str, Appui | None]:
    """(citation donnée par le modèle, morceau de passage retrouvé ou None)."""
    if not recherche.passages:
        return "", None
    citation = demander_citation(recherche, reponse, modeles)
    return citation, localiser(citation, [p for _, p in recherche.passages])
