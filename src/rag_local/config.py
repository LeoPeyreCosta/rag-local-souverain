"""Réglages, modifiables par variables d'environnement."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(nom: str, defaut: str) -> str:
    return os.environ.get(nom) or defaut


@dataclass
class Reglages:
    #: 127.0.0.1 plutôt que localhost : sous Windows, localhost essaie d'abord
    #: l'IPv6 (::1), où Ollama n'écoute pas, et chaque connexion perd environ
    #: 2 secondes avant de se rabattre sur l'IPv4.
    ollama_url: str = field(default_factory=lambda: _env("OLLAMA_URL", "http://127.0.0.1:11434"))
    modele_llm: str = field(default_factory=lambda: _env("LLM_MODEL", "mistral"))
    #: bge-m3 est multilingue ; nomic-embed-text, entraîné surtout sur de
    #: l'anglais, retrouve moins bien les passages en français (voir le README).
    modele_embeddings: str = field(default_factory=lambda: _env("EMBED_MODEL", "bge-m3"))
    dossier_documents: Path = field(default_factory=lambda: Path(_env("RAG_DOCUMENTS", "docs")))
    fichier_index: Path = field(default_factory=lambda: Path(_env("RAG_INDEX", "index.json")))
    #: Nombre de passages donnés au modèle pour répondre.
    nb_passages: int = 4
    taille_passage: int = 500  # caractères
    chevauchement: int = 80
