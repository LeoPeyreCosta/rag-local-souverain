"""Le contrat avec Ollama et la ligne de commande, sans réseau ni GPU."""

import json

import pytest
import requests
from conftest import ModelesFactices

from rag_local import __main__ as cli
from rag_local import ollama
from rag_local.ollama import ClientOllama
from rag_local.reponse import REFUS


# ------------------------------------------------------------------- Ollama
class ReponseHttp:
    def __init__(self, donnees=None, lignes=()):
        self.donnees, self.lignes = donnees, lignes

    def raise_for_status(self):
        pass

    def json(self):
        return self.donnees

    def iter_lines(self):
        yield from self.lignes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_vecteurs_demandes_par_lots(monkeypatch):
    envois = []

    def post(url, json, timeout):
        envois.append(json)
        return ReponseHttp({"embeddings": [[float(i)] for i in range(len(json["input"]))]})

    monkeypatch.setattr(ollama.requests, "post", post)
    vecteurs = ClientOllama(modele_embeddings="bge-m3").vecteurs([f"passage {i}" for i in range(40)], lot=32)
    assert len(vecteurs) == 40
    assert [len(e["input"]) for e in envois] == [32, 8]
    assert envois[0]["model"] == "bge-m3"


def test_reponse_lue_au_fil_de_l_eau(monkeypatch):
    lignes = [
        json.dumps({"message": {"content": "Deux "}}).encode(),
        b"",
        json.dumps({"message": {"content": "jours."}}).encode(),
        json.dumps({"message": {"content": ""}, "done": True}).encode(),
    ]
    envois = []

    def post(url, json, stream, timeout):
        envois.append(json)
        return ReponseHttp(lignes=lignes)

    monkeypatch.setattr(ollama.requests, "post", post)
    assert list(ClientOllama().repondre([{"role": "user", "content": "?"}])) == ["Deux ", "jours."]
    assert envois[0]["stream"] is True
    assert envois[0]["options"] == {"temperature": 0, "num_predict": 600}


def test_erreur_d_ollama_dans_le_flux(monkeypatch):
    lignes = [json.dumps({"error": "model not found"}).encode()]
    monkeypatch.setattr(ollama.requests, "post", lambda url, json, stream, timeout: ReponseHttp(lignes=lignes))
    with pytest.raises(RuntimeError, match="model not found"):
        list(ClientOllama().repondre([]))


def test_serveur_injoignable(monkeypatch):
    def get(*args, **kwargs):
        raise requests.ConnectionError("refusé")

    monkeypatch.setattr(ollama.requests, "get", get)
    client = ClientOllama()
    assert client.disponible() is False
    assert client.modeles_installes() == set()


# ------------------------------------------------------- ligne de commande
class ClientFactice(ModelesFactices):
    def __init__(self, url, modele_llm, modele_embeddings):
        super().__init__(
            "conges agent jours annuels teletravail semaine limite",
            reponse=lambda messages: ["Vous avez droit à 25 jours."]
            if "congés" in messages[-1]["content"][-40:] else [REFUS],
            modele_embeddings=modele_embeddings,
        )
        self.modele_llm = modele_llm

    def modeles_installes(self):
        return {"mistral"}


@pytest.fixture
def commande(monkeypatch, tmp_path, documents):
    monkeypatch.setattr(cli, "ClientOllama", ClientFactice)
    options = ["--documents", str(documents), "--index", str(tmp_path / "index.json")]
    return lambda *arguments: cli.main([arguments[0], *options, *arguments[1:]])


def test_indexer_demander_verifier(commande, capsys):
    commande("verifier")
    assert "à créer" in capsys.readouterr().out
    commande("indexer")
    assert "2 documents, 2 passages" in capsys.readouterr().out
    commande("demander", "Combien de jours de congés ?")
    sortie = capsys.readouterr().out
    assert "Vous avez droit à 25 jours." in sortie and "[1] conges.md" in sortie
    commande("demander", "Quel est le salaire du maire ?")
    sortie = capsys.readouterr().out
    assert REFUS in sortie and "Passages consultés" not in sortie  # pas de sources pour un refus
    commande("verifier")
    sortie = capsys.readouterr().out
    assert "2 passages" in sortie and "bge-m3 → absent" in sortie


def test_serveur_previent_s_il_est_ouvert_au_reseau(monkeypatch, commande, capsys):
    import uvicorn

    lancements = []
    monkeypatch.setattr(uvicorn, "run", lambda application, host, port, log_level: lancements.append(host))
    commande("serveur")
    assert "Attention" not in capsys.readouterr().err
    commande("serveur", "--hote", "0.0.0.0")
    assert "pas d'authentification" in capsys.readouterr().err
    assert lancements == ["127.0.0.1", "0.0.0.0"]


def test_evaluer_la_recherche(monkeypatch, tmp_path, documents, capsys):
    monkeypatch.setattr(cli, "ClientOllama", ClientFactice)
    questions = tmp_path / "questions.jsonl"
    questions.write_text(json.dumps({
        "id": "q1", "question": "jours de congés annuels", "source": "conges.md",
        "preuve": "25 jours de congés", "mots_cles": [["25"]],
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    cli.main([
        "evaluer", "--questions", str(questions), "--documents-evaluation", str(documents),
        "--embeddings", "bge-m3", "--details",
    ])
    sortie = capsys.readouterr().out
    assert "| bge-m3 | 1/1 (100%) | 1/1 (100%) | 1,00 |" in sortie
    assert "| bge-m3 | 1/1 (100%) | 0 | 0 |" in sortie
