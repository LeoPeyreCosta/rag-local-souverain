import json

import pytest
from conftest import ModelesFactices
from fastapi.testclient import TestClient

from rag_local import web
from rag_local.config import Reglages
from rag_local.reponse import REFUS
from rag_local.web import creer_application, nom_de_fichier_sur


@pytest.fixture
def application(tmp_path, documents):
    reglages = Reglages()
    reglages.dossier_documents = documents
    reglages.fichier_index = tmp_path / "index.json"
    modeles = ModelesFactices(
        "conges agent jours annuels teletravail semaine limite",
        reponse=lambda msgs: ["Vous avez ", "droit à 25 jours."] if "congés" in msgs[-1]["content"][-60:] else [REFUS],
    )
    return TestClient(creer_application(reglages, modeles))


def evenements(reponse) -> list[dict]:
    return [json.loads(ligne) for ligne in reponse.text.splitlines() if ligne.strip()]


def test_page_et_fichiers_statiques(application):
    page = application.get("/")
    assert page.status_code == 200 and '<html lang="fr">' in page.text
    assert application.get("/static/app.js").status_code == 200
    assert application.get("/docs").status_code == 404  # pas de documentation d'API exposée


def test_question_sans_index_puis_avec(application):
    assert application.post("/api/question", json={"question": "congés ?"}).status_code == 409
    etat = application.get("/api/etat").json()
    assert etat["index"] is None
    assert etat["documents"] == [{"nom": "conges.md", "indexe": False}, {"nom": "teletravail.md", "indexe": False}]

    bilan = application.post("/api/indexer").json()
    assert bilan["documents"] == 2 and bilan["passages"] == 2
    assert application.get("/api/etat").json()["index"]["passages"] == 2

    reponse = application.post("/api/question", json={"question": "Combien de jours de congés ?"})
    assert reponse.headers["content-type"].startswith("application/x-ndjson")
    flux = evenements(reponse)
    assert [e["type"] for e in flux] == ["sources", "texte", "texte", "fin"]
    assert flux[0]["passages"][0]["source"] == "conges.md"
    assert "".join(e["contenu"] for e in flux if e["type"] == "texte") == "Vous avez droit à 25 jours."
    assert flux[-1]["refus"] is False

    flux = evenements(application.post("/api/question", json={"question": "Le salaire du maire ?"}))
    assert flux[-1] == {**flux[-1], "type": "fin", "refus": True}


def test_question_vide_ou_trop_longue(application):
    application.post("/api/indexer")
    assert application.post("/api/question", json={"question": "   "}).status_code == 400
    assert application.post("/api/question", json={"question": "x" * 2001}).status_code == 400


def test_depot_de_documents(application, documents, monkeypatch):
    monkeypatch.setattr(web, "TAILLE_MAX", 100)
    reponse = application.post("/api/documents", files=[
        ("fichiers", ("../../note de service.md", b"Le mardi est obligatoire.", "text/markdown")),
        ("fichiers", ("programme.exe", b"MZ", "application/octet-stream")),
        ("fichiers", ("gros.txt", b"x" * 101, "text/plain")),
    ]).json()
    assert reponse["enregistres"] == ["note de service.md"]
    assert [r["nom"] for r in reponse["refuses"]] == ["programme.exe", "gros.txt"]
    assert (documents / "note de service.md").exists()  # dans le dossier des documents, pas au-dessus

    bilan = application.post("/api/indexer").json()
    assert bilan["recalcules"] == ["conges.md", "note de service.md", "teletravail.md"]
    bilan = application.post("/api/indexer").json()
    assert bilan["recalcules"] == [] and len(bilan["reutilises"]) == 3


def test_noms_de_fichiers_assainis():
    assert nom_de_fichier_sur("../../etc/passwd") == "passwd"
    assert nom_de_fichier_sur("..\\..\\Windows\\win.ini") == "win.ini"
    assert nom_de_fichier_sur("rapport <final>.pdf") == "rapport _final_.pdf"
    assert nom_de_fichier_sur("..") is None
