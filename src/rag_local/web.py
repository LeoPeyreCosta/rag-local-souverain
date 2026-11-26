"""Interface web : une petite API (FastAPI) et une page HTML sans framework.

    GET  /               la page
    GET  /api/etat       Ollama, modèles, index, documents
    POST /api/question   la réponse en flux NDJSON : passages, texte, appui, fin
    POST /api/documents  dépôt de fichiers .txt, .md, .pdf
    POST /api/indexer    mise à jour de l'index (seuls les documents modifiés sont recalculés)

Le serveur écoute par défaut sur 127.0.0.1 : la page n'est accessible que
depuis la machine. Il n'y a pas d'authentification ; l'ouvrir au réseau
local revient à donner accès aux documents à tous ceux qui s'y connectent.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Reglages
from .documents import EXTENSIONS, lire_documents
from .index import Index
from .ollama import ClientOllama, Modeles
from .reponse import appuyer, est_un_refus, rechercher, repondre

STATIQUE = Path(__file__).parent / "static"
TAILLE_MAX = 20 * 1024 * 1024  # octets par fichier déposé
LONGUEUR_MAX_QUESTION = 2000


class Question(BaseModel):
    question: str


def nom_de_fichier_sur(nom: str) -> str | None:
    """Nom de fichier sans chemin ni caractère spécial, ou None s'il ne reste
    rien d'utilisable. « ../../etc/passwd » devient « passwd »."""
    nom = re.split(r"[\\/]", nom or "")[-1]
    nom = re.sub(r"[^\w .-]", "_", nom).strip(" .")
    return nom or None


def _ligne(evenement: dict) -> str:
    return json.dumps(evenement, ensure_ascii=False) + "\n"


def creer_application(reglages: Reglages | None = None, modeles: Modeles | None = None) -> FastAPI:
    reglages = reglages or Reglages()
    modeles = modeles or ClientOllama(reglages.ollama_url, reglages.modele_llm, reglages.modele_embeddings)
    etat: dict[str, Index | None] = {"index": Index.charger(reglages.fichier_index)}
    indexation = threading.Lock()

    application = FastAPI(title="RAG local", docs_url=None, redoc_url=None, openapi_url=None)
    application.mount("/static", StaticFiles(directory=STATIQUE), name="static")

    @application.get("/", include_in_schema=False)
    def page() -> FileResponse:
        return FileResponse(STATIQUE / "index.html")

    @application.get("/api/etat")
    def lire_etat() -> dict:
        dossier = reglages.dossier_documents
        fichiers = sorted(
            p.relative_to(dossier).as_posix()
            for p in dossier.rglob("*")
            if p.is_file() and p.suffix.lower() in EXTENSIONS
        ) if dossier.exists() else []
        index = etat["index"]
        indexes = set(index.empreintes) if index else set()
        disponible = getattr(modeles, "disponible", lambda: True)()
        return {
            "ollama": disponible,
            "modele_llm": getattr(modeles, "modele_llm", reglages.modele_llm),
            "modele_embeddings": modeles.modele_embeddings,
            "index": {
                "passages": len(index.passages),
                "modele_embeddings": index.modele_embeddings,
            } if index else None,
            "documents": [{"nom": nom, "indexe": nom in indexes} for nom in fichiers],
        }

    @application.post("/api/question")
    def poser(entree: Question) -> StreamingResponse:
        question = entree.question.strip()
        if not question:
            raise HTTPException(400, "La question est vide.")
        if len(question) > LONGUEUR_MAX_QUESTION:
            raise HTTPException(400, f"La question dépasse {LONGUEUR_MAX_QUESTION} caractères.")
        index = etat["index"]
        if index is None:
            raise HTTPException(409, "Aucun index : ajoutez des documents, puis mettez l'index à jour.")

        def flux():
            depart = time.perf_counter()
            try:
                recherche = rechercher(question, index, modeles, reglages.nb_passages)
                yield _ligne({
                    "type": "sources",
                    "passages": [
                        {"rang": rang, "source": p.source, "texte": p.texte, "score": round(score, 3)}
                        for rang, (score, p) in enumerate(recherche.passages, start=1)
                    ],
                })
                texte = []
                for morceau in repondre(recherche, modeles):
                    texte.append(morceau)
                    yield _ligne({"type": "texte", "contenu": morceau})
                reponse = "".join(texte)
                refus = est_un_refus(reponse)
                if not refus:
                    yield _ligne({"type": "verification"})
                    _, appui = appuyer(recherche, reponse, modeles)
                    yield _ligne({"type": "appui", **(
                        {"trouve": True, "rang": appui.rang, "debut": appui.debut, "fin": appui.fin}
                        if appui else {"trouve": False}
                    )})
                yield _ligne({
                    "type": "fin",
                    "refus": refus,
                    "duree_s": round(time.perf_counter() - depart, 1),
                })
            except Exception as erreur:  # l'en-tête est déjà parti : on signale dans le flux
                yield _ligne({"type": "erreur", "message": str(erreur)})

        return StreamingResponse(flux(), media_type="application/x-ndjson")

    @application.post("/api/documents")
    async def deposer(fichiers: list[UploadFile] = File(...)) -> dict:
        reglages.dossier_documents.mkdir(parents=True, exist_ok=True)
        enregistres, refuses = [], []
        for fichier in fichiers:
            nom = nom_de_fichier_sur(fichier.filename or "")
            if nom is None or Path(nom).suffix.lower() not in EXTENSIONS:
                refuses.append({"nom": fichier.filename, "motif": "format accepté : .txt, .md ou .pdf"})
                continue
            contenu = await fichier.read(TAILLE_MAX + 1)
            if len(contenu) > TAILLE_MAX:
                refuses.append({"nom": nom, "motif": f"plus de {TAILLE_MAX // 1024 // 1024} Mo"})
                continue
            (reglages.dossier_documents / nom).write_bytes(contenu)
            enregistres.append(nom)
        return {"enregistres": enregistres, "refuses": refuses}

    @application.post("/api/indexer")
    def indexer() -> dict:
        if not indexation.acquire(blocking=False):
            raise HTTPException(409, "Une mise à jour de l'index est déjà en cours.")
        try:
            documents = lire_documents(reglages.dossier_documents) if reglages.dossier_documents.exists() else []
            if not documents:
                raise HTTPException(400, f"Aucun document lisible dans {reglages.dossier_documents}.")
            index, bilan = Index.construire(
                documents, modeles, etat["index"], reglages.taille_passage, reglages.chevauchement
            )
            index.enregistrer(reglages.fichier_index)
            etat["index"] = index
            return {
                "documents": bilan.documents,
                "passages": bilan.passages,
                "recalcules": bilan.recalcules,
                "reutilises": bilan.reutilises,
                "retires": bilan.retires,
            }
        finally:
            indexation.release()

    return application
