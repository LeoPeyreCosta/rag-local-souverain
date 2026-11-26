"""Faux modèles pour les tests : ni GPU, ni réseau, ni Ollama."""

from __future__ import annotations

import json
import re

import pytest

from rag_local.reponse import normaliser


class ModelesFactices:
    """Vecteurs « sac de mots » sur un vocabulaire fixé à l'avance : deux
    textes sont proches s'ils partagent des mots. La réponse est fournie par
    une fonction de la question et des extraits."""

    def __init__(self, vocabulaire: str, reponse=None, modele_embeddings: str = "faux", citation=None):
        self.vocabulaire = normaliser(vocabulaire).split()
        self.modele_embeddings = modele_embeddings
        self.reponse = reponse or (lambda messages: ["Réponse ", "factice."])
        #: Phrase que le faux modèle cite pour appuyer sa réponse.
        self.citation = citation or (lambda messages: "")
        self.textes_vectorises: list[str] = []
        self.demandes_json: list[list[dict]] = []

    def vecteurs(self, textes: list[str]) -> list[list[float]]:
        self.textes_vectorises += textes
        sacs = [set(normaliser(t).split()) for t in textes]
        return [[float(m in sac) for m in self.vocabulaire] for sac in sacs]

    def repondre(self, messages):
        yield from self.reponse(messages)

    def repondre_json(self, messages, schema):
        self.demandes_json.append(messages)
        return json.dumps({"citation": self.citation(messages)})

    def disponible(self) -> bool:
        return True


def question_posee(messages) -> str:
    return re.search(r"QUESTION : (.*)$", messages[-1]["content"], re.DOTALL).group(1)


@pytest.fixture
def documents(tmp_path):
    dossier = tmp_path / "docs"
    dossier.mkdir()
    (dossier / "conges.md").write_text(
        "# Congés\n\nUn agent a droit à 25 jours de congés annuels.\n", encoding="utf-8"
    )
    (dossier / "teletravail.md").write_text(
        "# Télétravail\n\nLe télétravail est limité à deux jours par semaine.\n", encoding="utf-8"
    )
    (dossier / "image.png").write_bytes(b"\x89PNG")  # ignoré : format non pris en charge
    return dossier


@pytest.fixture
def modeles():
    return ModelesFactices("conges agent jours annuels teletravail semaine limite")
