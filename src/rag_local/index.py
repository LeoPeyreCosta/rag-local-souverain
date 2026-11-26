"""Index des passages : construction, enregistrement, recherche.

L'index est un fichier JSON : pour chaque passage, son document d'origine,
son texte et son vecteur. La recherche compare le vecteur de la question à
celui de chaque passage (similarité cosinus), en Python pur : pour quelques
milliers de passages, une base vectorielle dédiée n'apporte rien.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .documents import decouper, empreinte
from .ollama import Modeles

VERSION = 2


@dataclass
class Passage:
    source: str
    texte: str
    vecteur: list[float]
    norme: float = 0.0

    def __post_init__(self) -> None:
        if not self.norme:
            self.norme = math.sqrt(sum(x * x for x in self.vecteur))


@dataclass
class Bilan:
    """Ce qu'une indexation a fait."""

    documents: int = 0
    recalcules: list[str] = field(default_factory=list)
    reutilises: list[str] = field(default_factory=list)
    retires: list[str] = field(default_factory=list)
    passages: int = 0


@dataclass
class Index:
    modele_embeddings: str
    passages: list[Passage] = field(default_factory=list)
    #: Empreinte du texte de chaque document indexé.
    empreintes: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------- fichier
    def enregistrer(self, chemin: Path) -> None:
        donnees = {
            "version": VERSION,
            "modele_embeddings": self.modele_embeddings,
            "documents": self.empreintes,
            "passages": [{"source": p.source, "texte": p.texte, "vecteur": p.vecteur} for p in self.passages],
        }
        chemin = Path(chemin)
        temporaire = chemin.with_suffix(".tmp")
        temporaire.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")
        temporaire.replace(chemin)  # un index à moitié écrit ne remplace jamais le bon

    @classmethod
    def charger(cls, chemin: Path) -> Index | None:
        """L'index enregistré, ou None s'il n'existe pas ou date d'un ancien format."""
        chemin = Path(chemin)
        if not chemin.exists():
            return None
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        if donnees.get("version") != VERSION:
            return None
        return cls(
            donnees["modele_embeddings"],
            [Passage(p["source"], p["texte"], p["vecteur"]) for p in donnees["passages"]],
            dict(donnees["documents"]),
        )

    # -------------------------------------------------------- construction
    @classmethod
    def construire(
        cls,
        documents: list[tuple[str, str]],
        modeles: Modeles,
        ancien: Index | None = None,
        taille: int = 500,
        chevauchement: int = 80,
    ) -> tuple[Index, Bilan]:
        """Indexe les documents. Les passages d'un document inchangé sont
        repris de l'ancien index (s'il utilise le même modèle d'embeddings) :
        seuls les documents nouveaux ou modifiés sont recalculés."""
        if ancien is not None and ancien.modele_embeddings != modeles.modele_embeddings:
            ancien = None
        index = cls(modeles.modele_embeddings)
        bilan = Bilan(documents=len(documents))
        a_calculer: list[tuple[str, list[str]]] = []
        for source, texte in documents:
            signature = empreinte(texte)
            index.empreintes[source] = signature
            if ancien is not None and ancien.empreintes.get(source) == signature:
                index.passages += [p for p in ancien.passages if p.source == source]
                bilan.reutilises.append(source)
            else:
                a_calculer.append((source, decouper(texte, taille, chevauchement)))
                bilan.recalcules.append(source)
        textes = [texte for _, morceaux in a_calculer for texte in morceaux]
        vecteurs = iter(modeles.vecteurs(textes) if textes else [])
        for source, morceaux in a_calculer:
            index.passages += [Passage(source, texte, next(vecteurs)) for texte in morceaux]
        if ancien is not None:
            bilan.retires = sorted(set(ancien.empreintes) - set(index.empreintes))
        bilan.passages = len(index.passages)
        return index, bilan

    # ------------------------------------------------------------ recherche
    def rechercher(self, vecteur: list[float], nombre: int) -> list[tuple[float, Passage]]:
        """Les ``nombre`` passages les plus proches, du plus au moins proche."""
        norme = math.sqrt(sum(x * x for x in vecteur))

        def similarite(passage: Passage) -> float:
            if not norme or not passage.norme:
                return 0.0
            return sum(a * b for a, b in zip(vecteur, passage.vecteur)) / (norme * passage.norme)

        scores = sorted(((similarite(p), p) for p in self.passages), key=lambda paire: -paire[0])
        return scores[:nombre]
