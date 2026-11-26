"""Client du serveur Ollama local : embeddings et réponses du modèle."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import requests


class Modeles(Protocol):
    """Ce dont le RAG a besoin : des vecteurs et un modèle qui répond."""

    modele_embeddings: str

    def vecteurs(self, textes: list[str]) -> list[list[float]]: ...

    def repondre(self, messages: list[dict[str, str]]) -> Iterator[str]: ...


@dataclass
class ClientOllama:
    url: str = "http://localhost:11434"
    modele_llm: str = "mistral"
    modele_embeddings: str = "bge-m3"

    def disponible(self) -> bool:
        try:
            requests.get(f"{self.url}/api/tags", timeout=3).raise_for_status()
            return True
        except requests.RequestException:
            return False

    def modeles_installes(self) -> set[str]:
        try:
            modeles = requests.get(f"{self.url}/api/tags", timeout=5).json().get("models", [])
        except (requests.RequestException, ValueError):
            return set()
        return {m.get("name", "").split(":")[0] for m in modeles}

    def vecteurs(self, textes: list[str], lot: int = 32) -> list[list[float]]:
        resultat: list[list[float]] = []
        for debut in range(0, len(textes), lot):
            reponse = requests.post(
                f"{self.url}/api/embed",
                json={"model": self.modele_embeddings, "input": textes[debut : debut + lot]},
                timeout=300,
            )
            reponse.raise_for_status()
            resultat += reponse.json()["embeddings"]
        return resultat

    def repondre(self, messages: list[dict[str, str]]) -> Iterator[str]:
        """Réponse du modèle, morceau par morceau, au fur et à mesure qu'il l'écrit."""
        with requests.post(
            f"{self.url}/api/chat",
            json={
                "model": self.modele_llm,
                "messages": messages,
                "stream": True,
                "options": {"temperature": 0, "num_predict": 600},
            },
            stream=True,
            timeout=600,
        ) as reponse:
            reponse.raise_for_status()
            for ligne in reponse.iter_lines():
                if not ligne:
                    continue
                morceau = json.loads(ligne)
                if morceau.get("error"):
                    raise RuntimeError(morceau["error"])
                texte = morceau.get("message", {}).get("content", "")
                if texte:
                    yield texte
                if morceau.get("done"):
                    break
