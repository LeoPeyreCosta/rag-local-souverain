"""Mesure de la recherche et des réponses sur des questions annotées.

Chaque question (``questions.jsonl``) donne la phrase du document qui
contient la réponse (``preuve``) et les mots qu'une réponse juste doit
contenir (``mots_cles`` : pour chaque groupe, au moins un mot qui commence
par l'un des termes, sans tenir compte des accents ni des majuscules).
Une question sans réponse dans les documents a ``preuve`` à null.

Indicateurs :

* **recherche** : rang du premier passage qui contient la preuve. On compte
  les questions où il arrive en tête, et celles où il figure parmi les
  passages donnés au modèle (les 4 premiers) ;
* **réponses** : juste, refus à tort (« je ne trouve pas » alors que
  l'information est là), fausse ; pour les questions sans réponse, refus
  correct ou réponse inventée.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .index import Index
from .ollama import Modeles
from .reponse import est_un_refus, normaliser, rechercher, repondre


def lire_questions(chemin: Path) -> list[dict]:
    lignes = Path(chemin).read_text(encoding="utf-8").splitlines()
    return [json.loads(ligne) for ligne in lignes if ligne.strip()]


def correspond(texte: str, groupes: list[list[str]]) -> bool:
    normal = normaliser(texte)
    return all(
        any(re.search(rf"(?<![a-z0-9]){re.escape(normaliser(terme))}", normal) for terme in groupe)
        for groupe in groupes
    )


# --------------------------------------------------------------- recherche
@dataclass
class MesureRecherche:
    modele: str
    questions: int = 0
    en_tete: int = 0
    parmi_k: int = 0
    inverse_rangs: float = 0.0  # somme des 1/rang, pour le rang réciproque moyen
    rates: list[str] = field(default_factory=list)

    @property
    def rang_reciproque_moyen(self) -> float:
        return self.inverse_rangs / self.questions if self.questions else 0.0


def mesurer_recherche(questions: list[dict], index: Index, modeles: Modeles, k: int = 4) -> MesureRecherche:
    mesure = MesureRecherche(index.modele_embeddings)
    avec_reponse = [q for q in questions if q["preuve"]]
    vecteurs = modeles.vecteurs([q["question"] for q in avec_reponse])
    for question, vecteur in zip(avec_reponse, vecteurs):
        mesure.questions += 1
        preuve = normaliser(question["preuve"])
        classement = index.rechercher(vecteur, len(index.passages))
        rang = next((i for i, (_, p) in enumerate(classement, start=1) if preuve in normaliser(p.texte)), None)
        if rang is None:
            raise ValueError(f"{question['id']} : preuve introuvable dans l'index : {question['preuve']!r}")
        mesure.en_tete += rang == 1
        mesure.parmi_k += rang <= k
        mesure.inverse_rangs += 1 / rang
        if rang > k:
            mesure.rates.append(f"{question['id']} (rang {rang}) : {question['question']}")
    return mesure


# ---------------------------------------------------------------- réponses
@dataclass
class MesureReponses:
    modele: str
    avec_reponse: int = 0
    justes: int = 0
    refus_a_tort: int = 0
    fausses: int = 0
    sans_reponse: int = 0
    refus_corrects: int = 0
    inventees: int = 0
    duree_s: float = 0.0
    erreurs: list[str] = field(default_factory=list)


def mesurer_reponses(questions: list[dict], index: Index, modeles: Modeles, k: int = 4) -> MesureReponses:
    mesure = MesureReponses(index.modele_embeddings)
    depart = time.perf_counter()
    for question in questions:
        texte = "".join(repondre(rechercher(question["question"], index, modeles, k), modeles)).strip()
        refus = est_un_refus(texte)
        resume = f"{question['id']} : {question['question']} → {texte}"
        if question["preuve"]:
            mesure.avec_reponse += 1
            if refus:
                mesure.refus_a_tort += 1
                mesure.erreurs.append("refus à tort — " + resume)
            elif correspond(texte, question["mots_cles"]):
                mesure.justes += 1
            else:
                mesure.fausses += 1
                mesure.erreurs.append("réponse fausse — " + resume)
        else:
            mesure.sans_reponse += 1
            if refus:
                mesure.refus_corrects += 1
            else:
                mesure.inventees += 1
                mesure.erreurs.append("réponse inventée — " + resume)
    mesure.duree_s = time.perf_counter() - depart
    return mesure


# ----------------------------------------------------------------- tableaux
def _part(n: int, total: int) -> str:
    return f"{n}/{total} ({n / total:.0%})" if total else "–"


def tableau_recherche(mesures: list[MesureRecherche], k: int = 4) -> str:
    lignes = [
        f"| Embeddings | Passage juste en tête | Parmi les {k} premiers | Rang réciproque moyen |",
        "|---|---|---|---|",
    ]
    lignes += [
        f"| {m.modele} | {_part(m.en_tete, m.questions)} | {_part(m.parmi_k, m.questions)} "
        f"| {m.rang_reciproque_moyen:.2f} |".replace(".", ",")
        for m in mesures
    ]
    return "\n".join(lignes)


def tableau_reponses(mesures: list[MesureReponses]) -> str:
    lignes = [
        "| Embeddings | Réponses justes | Refus à tort | Réponses fausses | Refus corrects (sans réponse) "
        "| Réponses inventées | Durée par question |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in mesures:
        total = m.avec_reponse + m.sans_reponse
        lignes.append(
            f"| {m.modele} | {_part(m.justes, m.avec_reponse)} | {m.refus_a_tort} | {m.fausses} "
            f"| {_part(m.refus_corrects, m.sans_reponse)} | {m.inventees} "
            f"| {m.duree_s / total:.1f} s |".replace(".", ",") if total else ""
        )
    return "\n".join(lignes)
