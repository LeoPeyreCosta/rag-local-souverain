"""Ligne de commande.

    rag-local verifier                 Ollama, modèles, index
    rag-local indexer                  indexe les documents de ./docs
    rag-local demander "question ?"    répond dans le terminal
    rag-local serveur                  interface web sur http://127.0.0.1:8000
    rag-local evaluer                  mesure la recherche et les réponses
"""

from __future__ import annotations

import argparse
import ipaddress
import sys
from pathlib import Path

from .config import Reglages
from .documents import lire_documents
from .evaluation import (
    lire_questions,
    mesurer_recherche,
    mesurer_reponses,
    tableau_appuis,
    tableau_recherche,
    tableau_reponses,
)
from .index import Index
from .ollama import ClientOllama
from .reponse import appuyer, est_un_refus, rechercher, repondre


def _reglages(args: argparse.Namespace) -> Reglages:
    reglages = Reglages()
    if getattr(args, "documents", None):
        reglages.dossier_documents = Path(args.documents)
    if getattr(args, "index", None):
        reglages.fichier_index = Path(args.index)
    return reglages


def _client(reglages: Reglages, embeddings: str | None = None) -> ClientOllama:
    client = ClientOllama(reglages.ollama_url, reglages.modele_llm, embeddings or reglages.modele_embeddings)
    if not client.disponible():
        sys.exit(f"Ollama est injoignable sur {reglages.ollama_url}. Lancez « ollama serve ».")
    return client


def _verifier(args: argparse.Namespace) -> None:
    reglages = _reglages(args)
    client = ClientOllama(reglages.ollama_url, reglages.modele_llm, reglages.modele_embeddings)
    disponible = client.disponible()
    print(f"Ollama      : {reglages.ollama_url} → {'OK' if disponible else 'injoignable (ollama serve)'}")
    if disponible:
        installes = client.modeles_installes()
        for role, modele in (("Modèle", reglages.modele_llm), ("Embeddings", reglages.modele_embeddings)):
            etat = "OK" if modele.split(":")[0] in installes else f"absent (ollama pull {modele})"
            print(f"{role:<11} : {modele} → {etat}")
    index = Index.charger(reglages.fichier_index)
    print(f"Index       : {reglages.fichier_index} → "
          + (f"{len(index.passages)} passages ({index.modele_embeddings})" if index else "à créer (rag-local indexer)"))


def _indexer(args: argparse.Namespace) -> None:
    reglages = _reglages(args)
    documents = lire_documents(reglages.dossier_documents) if reglages.dossier_documents.exists() else []
    if not documents:
        sys.exit(f"Aucun document .txt, .md ou .pdf dans {reglages.dossier_documents}.")
    index, bilan = Index.construire(
        documents, _client(reglages), Index.charger(reglages.fichier_index),
        reglages.taille_passage, reglages.chevauchement,
    )
    index.enregistrer(reglages.fichier_index)
    print(f"{bilan.documents} documents, {bilan.passages} passages → {reglages.fichier_index}")
    print(f"  recalculés : {len(bilan.recalcules)}, inchangés : {len(bilan.reutilises)}, retirés : {len(bilan.retires)}")


def _demander(args: argparse.Namespace) -> None:
    reglages = _reglages(args)
    index = Index.charger(reglages.fichier_index)
    if index is None:
        sys.exit("Pas d'index. Lancez d'abord : rag-local indexer")
    client = _client(reglages, index.modele_embeddings)
    recherche = rechercher(args.question, index, client, reglages.nb_passages)
    texte = []
    print()
    for morceau in repondre(recherche, client):
        texte.append(morceau)
        print(morceau, end="", flush=True)
    print("\n")
    reponse = "".join(texte)
    if not est_un_refus(reponse):
        _, appui = appuyer(recherche, reponse, client)
        if appui:
            passage = recherche.passages[appui.rang - 1][1]
            cite = " ".join(passage.texte[appui.debut : appui.fin].split())
            print(f"Phrase qui appuie la réponse [{appui.rang}] {passage.source} :\n  « {cite} »\n")
        else:
            print("Réponse non vérifiée : aucune phrase des passages n'a pu lui être rattachée.\n")
        print("Passages consultés (du plus au moins proche) :")
        for rang, (score, passage) in enumerate(recherche.passages, start=1):
            extrait = " ".join(passage.texte.split())[:80]
            print(f"  [{rang}] {passage.source} ({score:.2f}) : {extrait}…")


def _serveur(args: argparse.Namespace) -> None:
    import uvicorn

    from .web import creer_application

    try:
        locale = ipaddress.ip_address(args.hote).is_loopback
    except ValueError:
        locale = args.hote == "localhost"
    if not locale:
        print(
            f"Attention : sur {args.hote}, toute personne qui atteint cette machine peut lire les "
            "documents et en ajouter. Il n'y a pas d'authentification.",
            file=sys.stderr,
        )
    print(f"Interface : http://{args.hote}:{args.port}")
    uvicorn.run(creer_application(_reglages(args)), host=args.hote, port=args.port, log_level="warning")


def _evaluer(args: argparse.Namespace) -> None:
    reglages = _reglages(args)
    questions = lire_questions(Path(args.questions))
    documents = lire_documents(Path(args.documents_evaluation))
    recherches, reponses = [], []
    for modele in args.embeddings.split(","):
        client = _client(reglages, modele)
        index, _ = Index.construire(documents, client, None, reglages.taille_passage, reglages.chevauchement)
        recherches.append(mesurer_recherche(questions, index, client, reglages.nb_passages))
        if not args.sans_reponses:
            reponses.append(mesurer_reponses(questions, index, client, reglages.nb_passages, not args.sans_appui))
    avec = sum(1 for q in questions if q["preuve"])
    print(f"{len(questions)} questions ({avec} avec réponse dans les documents), "
          f"{len(documents)} documents, {len(index.passages)} passages\n")
    print(tableau_recherche(recherches, reglages.nb_passages))
    if reponses:
        print()
        print(tableau_reponses(reponses))
        if not args.sans_appui:
            print()
            print(tableau_appuis(reponses))
    if args.details:
        for mesure in recherches:
            if mesure.rates:
                print(f"\nRecherche ({mesure.modele}), passage absent des {reglages.nb_passages} premiers :")
                print("\n".join(f"  - {r}" for r in mesure.rates))
        for mesure_reponses in reponses:
            if mesure_reponses.erreurs:
                print(f"\nRéponses ({mesure_reponses.modele}) :")
                print("\n".join(f"  - {e}" for e in mesure_reponses.erreurs))
            if mesure_reponses.appuis:
                print(f"\nAppuis ({mesure_reponses.modele}) :")
                print("\n".join(f"  - {a}" for a in mesure_reponses.appuis))


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="rag-local", description="Interroger ses documents avec un modèle 100 % local.")
    commun = argparse.ArgumentParser(add_help=False)
    commun.add_argument("--documents", help="dossier des documents (défaut : docs)")
    commun.add_argument("--index", help="fichier de l'index (défaut : index.json)")
    sous = parser.add_subparsers(dest="commande", required=True)

    sous.add_parser("verifier", parents=[commun], help="vérifier Ollama, les modèles et l'index").set_defaults(f=_verifier)
    sous.add_parser("indexer", parents=[commun], help="indexer les documents").set_defaults(f=_indexer)
    p = sous.add_parser("demander", parents=[commun], help="poser une question")
    p.add_argument("question")
    p.set_defaults(f=_demander)
    p = sous.add_parser("serveur", parents=[commun], help="lancer l'interface web")
    p.add_argument("--hote", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(f=_serveur)
    p = sous.add_parser("evaluer", help="mesurer la recherche et les réponses")
    p.add_argument("--questions", default="corpus/developpement/questions.jsonl")
    p.add_argument("--documents-evaluation", default="corpus/documents")
    p.add_argument("--embeddings", default="bge-m3,nomic-embed-text", help="modèles d'embeddings à comparer")
    p.add_argument("--sans-reponses", action="store_true", help="mesurer la recherche seulement (rapide)")
    p.add_argument("--sans-appui", action="store_true", help="ne pas vérifier les réponses par une citation")
    p.add_argument("--details", action="store_true")
    p.set_defaults(f=_evaluer)

    args = parser.parse_args(argv)
    args.f(args)


if __name__ == "__main__":
    main()
