#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAG local souverain — interroger ses documents privés avec un LLM 100 % local.

Aucune donnée ne quitte la machine : le seul réseau utilisé est localhost:11434
(le serveur Ollama). Fonctionne hors ligne, câble débranché.

Dépendances : requests, pypdf  (déjà présentes, aucun pip install).
Moteur      : Ollama (LLM + embeddings), tourne sur le GPU local.

Usage :
    python rag_local.py ingest                 # indexe les fichiers de ./docs
    python rag_local.py ask "ma question ?"    # interroge l'index
    python rag_local.py check                  # vérifie Ollama + les modèles
"""

import os
import re
import sys
import json
import math
import glob

import requests

# ---------------------------------------------------------------- configuration
OLLAMA_URL   = os.environ.get("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL    = os.environ.get("LLM_MODEL", "mistral")            # ollama pull mistral
EMBED_MODEL  = os.environ.get("EMBED_MODEL", "nomic-embed-text") # ollama pull nomic-embed-text
HERE         = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR     = os.path.join(HERE, "docs")
INDEX_PATH   = os.path.join(HERE, "index.json")
TOP_K        = 4        # nb de passages donnés au LLM
CHUNK_SIZE   = 500      # taille d'un passage (caractères)
CHUNK_OVER   = 80       # chevauchement entre passages


# ------------------------------------------------------------------ lecture docs
def lire_fichier(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md"):
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            print("  ! pypdf manquant pour lire les PDF — ignoré :", path)
            return ""
        txt = []
        for page in PdfReader(path).pages:
            txt.append(page.extract_text() or "")
        return "\n".join(txt)
    return ""


def lire_documents(docs_dir):
    docs = []
    for path in sorted(glob.glob(os.path.join(docs_dir, "**", "*"), recursive=True)):
        if os.path.isfile(path):
            texte = lire_fichier(path)
            if texte.strip():
                docs.append((os.path.relpath(path, docs_dir), texte))
    return docs


def decouper(texte, size=CHUNK_SIZE, overlap=CHUNK_OVER):
    texte = re.sub(r"[ \t]+", " ", texte).strip()
    morceaux, i, n = [], 0, len(texte)
    while i < n:
        fin = min(i + size, n)
        coupe = texte.rfind("\n", i + int(size * 0.6), fin)
        if coupe == -1:
            coupe = texte.rfind(" ", i + int(size * 0.6), fin)
        if coupe == -1 or fin == n:
            coupe = fin
        bloc = texte[i:coupe].strip()
        if bloc:
            morceaux.append(bloc)
        if coupe >= n:
            break
        i = max(coupe - overlap, i + 1)
        espace = texte.find(" ", i)          # démarrer sur un début de mot
        if espace != -1 and espace < coupe:
            i = espace + 1
    return morceaux


# -------------------------------------------------------------------- ollama API
def ollama_up():
    try:
        requests.get(OLLAMA_URL + "/api/tags", timeout=3).raise_for_status()
        return True
    except Exception:
        return False


def modeles_presents():
    try:
        tags = requests.get(OLLAMA_URL + "/api/tags", timeout=5).json().get("models", [])
        noms = {m.get("name", "").split(":")[0] for m in tags}
        return noms
    except Exception:
        return set()


def embed(texte):
    r = requests.post(OLLAMA_URL + "/api/embeddings",
                      json={"model": EMBED_MODEL, "prompt": texte}, timeout=120)
    r.raise_for_status()
    return r.json()["embedding"]


def chat(messages):
    r = requests.post(OLLAMA_URL + "/api/chat",
                      json={"model": LLM_MODEL, "messages": messages, "stream": False},
                      timeout=600)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


# ------------------------------------------------------------------- similarité
def norme(v):
    return math.sqrt(sum(x * x for x in v))


def cosinus(a, na, b, nb):
    if not na or not nb:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


# ---------------------------------------------------------------------- commandes
def cmd_check():
    print("Ollama     :", OLLAMA_URL, "->", "OK" if ollama_up() else "INJOIGNABLE (lance 'ollama serve')")
    if ollama_up():
        presents = modeles_presents()
        for role, modele in (("LLM", LLM_MODEL), ("Embeddings", EMBED_MODEL)):
            etat = "OK" if modele.split(":")[0] in presents else f"ABSENT (ollama pull {modele})"
            print(f"{role:11}: {modele} -> {etat}")
    print("Index      :", INDEX_PATH, "->", "présent" if os.path.exists(INDEX_PATH) else "à créer (ingest)")


def cmd_ingest():
    if not ollama_up():
        sys.exit("Ollama injoignable. Lance 'ollama serve' (ou l'appli Ollama) puis réessaie.")
    docs = lire_documents(DOCS_DIR)
    if not docs:
        sys.exit(f"Aucun document dans {DOCS_DIR} (ajoute des .txt / .md / .pdf).")
    index = []
    for source, texte in docs:
        passages = decouper(texte)
        print(f"  {source} : {len(passages)} passage(s)")
        for p in passages:
            v = embed(p)
            index.append({"source": source, "texte": p, "vec": v, "norme": norme(v)})
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump({"embed_model": EMBED_MODEL, "chunks": index}, f, ensure_ascii=False)
    print(f"Index écrit : {len(index)} passage(s) -> {INDEX_PATH}")


def cmd_ask(question):
    if not os.path.exists(INDEX_PATH):
        sys.exit("Pas d'index. Lance d'abord : python rag_local.py ingest")
    if not ollama_up():
        sys.exit("Ollama injoignable. Lance 'ollama serve' puis réessaie.")
    data = json.load(open(INDEX_PATH, encoding="utf-8"))
    chunks = data["chunks"]

    qv = embed(question)
    qn = norme(qv)
    classés = sorted(chunks, key=lambda c: cosinus(qv, qn, c["vec"], c["norme"]), reverse=True)
    retenus = classés[:TOP_K]

    contexte = "\n\n".join(f"[{i+1}] (source : {c['source']})\n{c['texte']}"
                           for i, c in enumerate(retenus))
    # Les sources sont affichées par le programme (fiable), pas citées par le
    # modèle : un petit LLM (7B) numérote souvent mal ses références.
    systeme = ("Tu réponds uniquement à partir du CONTEXTE fourni, en français, "
               "de façon concise. Si l'information n'y est pas, dis-le clairement. "
               "N'ajoute aucun numéro de référence.")
    user = f"CONTEXTE :\n{contexte}\n\nQUESTION : {question}"
    reponse = chat([{"role": "system", "content": systeme},
                    {"role": "user", "content": user}])

    print("\n" + reponse + "\n")
    print("— Passages consultés (du plus au moins pertinent) —")
    for i, c in enumerate(retenus):
        extrait = c["texte"].replace("\n", " ")[:70]
        print(f"  [{i+1}] {c['source']} : {extrait}…")


# --------------------------------------------------------------------------- main
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "ingest":
        cmd_ingest()
    elif cmd == "ask" and len(sys.argv) > 2:
        cmd_ask(" ".join(sys.argv[2:]))
    elif cmd == "check":
        cmd_check()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
