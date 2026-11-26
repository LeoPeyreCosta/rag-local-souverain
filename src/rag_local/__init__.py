"""RAG local souverain : interroger ses documents avec un modèle qui tourne
sur la machine (Ollama), en ligne de commande ou par une interface web."""

from .config import Reglages
from .index import Index, Passage
from .ollama import ClientOllama
from .reponse import REFUS, est_un_refus, rechercher, repondre

__all__ = ["REFUS", "ClientOllama", "Index", "Passage", "Reglages", "est_un_refus", "rechercher", "repondre"]
__version__ = "0.2.0"
