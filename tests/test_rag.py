import json

import pytest
from conftest import ModelesFactices, question_posee

from rag_local.documents import decouper, lire_documents
from rag_local.evaluation import correspond, mesurer_recherche, mesurer_reponses
from rag_local.index import Index
from rag_local.reponse import REFUS, est_un_refus, messages, rechercher, repondre


# -------------------------------------------------------------- documents
def test_decoupage_avec_chevauchement():
    texte = " ".join(f"mot{i}" for i in range(400))
    passages = decouper(texte, taille=200, chevauchement=40)
    assert len(passages) > 5
    assert all(len(p) <= 200 for p in passages)
    assert all(not p.startswith(" ") and p for p in passages)
    assert passages[1].split()[0] in passages[0]  # le passage suivant reprend la fin du précédent
    assert passages[-1].endswith("mot399")


def test_lecture_des_documents(documents):
    assert [source for source, _ in lire_documents(documents)] == ["conges.md", "teletravail.md"]


# ------------------------------------------------------------------ index
def test_recherche_du_passage_le_plus_proche(documents, modeles):
    index, bilan = Index.construire(lire_documents(documents), modeles)
    assert bilan.recalcules == ["conges.md", "teletravail.md"] and bilan.passages == 2
    recherche = rechercher("Combien de jours de congés annuels ?", index, modeles, nombre=1)
    assert recherche.passages[0][1].source == "conges.md"


def test_indexation_incrementale(documents, modeles):
    index, _ = Index.construire(lire_documents(documents), modeles)
    (documents / "teletravail.md").write_text("Le télétravail : trois jours par semaine.", encoding="utf-8")
    (documents / "conges.md").unlink()
    (documents / "nouveau.txt").write_text("Les agents ont une semaine de plus.", encoding="utf-8")
    modeles.textes_vectorises.clear()
    nouvel_index, bilan = Index.construire(lire_documents(documents), modeles, index)
    assert bilan.reutilises == [] and sorted(bilan.recalcules) == ["nouveau.txt", "teletravail.md"]
    assert bilan.retires == ["conges.md"]
    assert {p.source for p in nouvel_index.passages} == {"nouveau.txt", "teletravail.md"}

    modeles.textes_vectorises.clear()
    _, bilan = Index.construire(lire_documents(documents), modeles, nouvel_index)
    assert sorted(bilan.reutilises) == ["nouveau.txt", "teletravail.md"]
    assert modeles.textes_vectorises == []  # rien n'a été recalculé


def test_changement_de_modele_d_embeddings_recalcule_tout(documents, modeles):
    index, _ = Index.construire(lire_documents(documents), modeles)
    autre = ModelesFactices("conges semaine", modele_embeddings="autre")
    _, bilan = Index.construire(lire_documents(documents), autre, index)
    assert bilan.reutilises == [] and len(bilan.recalcules) == 2
    with pytest.raises(ValueError, match="réindexez"):
        rechercher("congés", index, autre)


def test_index_enregistre_et_relu(tmp_path, documents, modeles):
    index, _ = Index.construire(lire_documents(documents), modeles)
    chemin = tmp_path / "index.json"
    index.enregistrer(chemin)
    relu = Index.charger(chemin)
    assert relu.modele_embeddings == "faux" and len(relu.passages) == 2
    assert relu.empreintes == index.empreintes
    chemin.write_text(json.dumps({"embed_model": "nomic-embed-text", "chunks": []}), encoding="utf-8")
    assert Index.charger(chemin) is None  # ancien format : à reconstruire


# ---------------------------------------------------------------- réponse
def test_refus_reconnu():
    assert est_un_refus(REFUS)
    assert est_un_refus("Désolé. JE NE TROUVE PAS cette information dans les documents fournis.")
    # Le modèle reformule parfois la phrase imposée :
    assert est_un_refus("La cantine du personnel n'est pas mentionnée dans les extraits fournis.")
    assert est_un_refus("Les informations fournies ne précisent pas quel jour.")
    assert not est_un_refus("Vous avez droit à 25 jours.")
    assert not est_un_refus("Les amendes ne sont pas remboursées.")  # une négation n'est pas un refus


def test_consigne_et_extraits(documents, modeles):
    index, _ = Index.construire(lire_documents(documents), modeles)
    recherche = rechercher("jours de congés", index, modeles, nombre=2)
    contenu = messages(recherche.question, [p for _, p in recherche.passages])
    assert REFUS in contenu[0]["content"]
    assert "[1] (source : conges.md)" in contenu[1]["content"]
    assert contenu[1]["content"].endswith("QUESTION : jours de congés")


def test_index_vide_donne_le_refus(modeles):
    recherche = rechercher("question", Index("faux"), modeles)
    assert "".join(repondre(recherche, modeles)) == REFUS


# ------------------------------------------------------------- évaluation
def test_correspondance_des_mots_cles():
    assert correspond("Vous avez droit à 25 jours.", [["25"]])
    assert not correspond("Vous avez droit à 125 jours.", [["25"]])  # début de mot seulement
    assert correspond("Le mardi, présence obligatoire", [["mardi"], ["obligatoire", "oblig"]])


def test_mesures_de_recherche_et_de_reponse(documents):
    questions = [
        {"id": "q1", "question": "jours de congés annuels", "preuve": "25 jours de congés", "mots_cles": [["25"]]},
        {"id": "q2", "question": "télétravail par semaine", "preuve": "deux jours par semaine", "mots_cles": [["deux", "2"]]},
        {"id": "q3", "question": "agent congés", "preuve": "25 jours", "mots_cles": [["25"]]},
        {"id": "q4", "question": "prime de fin d'année", "preuve": None, "mots_cles": None},
        {"id": "q5", "question": "salaire du maire", "preuve": None, "mots_cles": None},
    ]
    reponses = {
        "jours de congés annuels": ["Vous avez droit à 25 jours."],
        "télétravail par semaine": [REFUS],
        "agent congés": ["Trente jours."],
        "prime de fin d'année": [REFUS],
        "salaire du maire": ["Il gagne 3000 euros."],
    }
    modeles = ModelesFactices(
        "conges agent jours annuels teletravail semaine limite",
        reponse=lambda msgs: reponses[question_posee(msgs)],
    )
    index, _ = Index.construire(lire_documents(documents), modeles)
    recherche = mesurer_recherche(questions, index, modeles, k=1)
    assert (recherche.questions, recherche.en_tete, recherche.parmi_k) == (3, 3, 3)
    mesure = mesurer_reponses(questions, index, modeles, k=1)
    assert (mesure.justes, mesure.refus_a_tort, mesure.fausses) == (1, 1, 1)
    assert (mesure.refus_corrects, mesure.inventees) == (1, 1)
    assert any(e.startswith("réponse inventée — q5") for e in mesure.erreurs)


def test_preuve_absente_de_l_index(documents, modeles):
    index, _ = Index.construire(lire_documents(documents), modeles)
    with pytest.raises(ValueError, match="preuve introuvable"):
        mesurer_recherche([{"id": "x", "question": "congés", "preuve": "n'existe pas", "mots_cles": []}], index, modeles)
