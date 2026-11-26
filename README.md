# RAG local souverain

**Interroger ses documents privés avec un LLM qui tourne entièrement sur sa propre machine — sans qu'aucune donnée ne quitte le réseau local.**

Cas d'usage : un service (santé, administration, cabinet, PME) veut poser des questions en langage naturel sur ses documents internes — notes, procédures, dossiers — **sans envoyer ces données dans le cloud**. C'est l'approche « IA souveraine » : confidentialité par conception, utilisable même sur un réseau isolé (*air-gapped*).

---

## Ce que ça fait

On dépose des documents dans `docs/` (`.txt`, `.md`, `.pdf`). Le programme les découpe, les transforme en vecteurs (*embeddings*) **en local**, et les range dans un index. Quand on pose une question, il retrouve les passages les plus pertinents et les donne à un LLM **local** qui rédige la réponse ; le programme affiche ensuite les passages consultés, du plus au moins pertinent.

```
  Documents privés (docs/)
        │
        ▼
  Découpage en passages
        │
        ▼
  Embeddings  ──►  Ollama (nomic-embed-text)   [GPU local]
        │
        ▼
  Index local (index.json)
        ▲
        │  recherche par similarité
  Question ──► embedding ──┘
        │
        ▼
  Passages pertinents  ──►  LLM  ──►  Ollama (mistral)  [GPU local]
        │
        ▼
  Réponse + passages consultés

  ── Tout le trafic reste sur localhost:11434. Rien ne sort. ──
```

## Souveraineté : les garanties

- **Aucun appel externe.** Le seul réseau utilisé est `http://localhost:11434` (le serveur Ollama, sur la machine). Aucune clé d'API, aucun service cloud.
- **Fonctionne hors ligne.** Une fois les deux modèles téléchargés, on peut **débrancher le réseau** : l'indexation et les questions marchent toujours.
- **Vérifiable.** Pour le prouver : couper le Wi-Fi / débrancher le câble, puis relancer `python rag_local.py ask "..."` — ça répond. On peut aussi surveiller le trafic (Wireshark, pare-feu) : seul localhost apparaît.
- **Les données restent chez soi.** Les documents, l'index et les réponses ne sont écrits que sur le disque local.

## Stack

| Élément | Choix | Pourquoi |
|---|---|---|
| Serveur de modèles | **Ollama** | Simple, local, API compatible, tourne sur le GPU |
| LLM | **mistral** (7B) | Léger, bon en français, tient dans 10 Go de VRAM |
| Embeddings | **nomic-embed-text** | Modèle d'embeddings local, rapide |
| Recherche vectorielle | Python pur (cosinus) | Aucune dépendance lourde, transparent |
| Lecture PDF | pypdf | — |
| Matériel de test | RTX 3080 (10 Go) | Suffisant pour du 7–8B quantifié |

Dépendances Python : `requests`, `pypdf` **uniquement** (aucune installation lourde).

## Quel matériel pour faire tourner ça ?

**La règle :** le modèle doit tenir dans la mémoire de la carte graphique (VRAM). Ici, `mistral` 7B quantifié pèse environ 4,4 Go et le modèle d'embeddings 0,3 Go : **8 Go de VRAM suffisent pour un utilisateur**. Plus de VRAM permet des modèles plus gros (meilleures réponses) ou plusieurs utilisateurs simultanés.

| Usage | Matériel type | Mémoire | Prix indicatif | Ce que ça permet |
|---|---|---|---|---|
| Découverte | PC existant, sans carte graphique (16 Go de RAM) | — | 0 € | Fonctionne sur le processeur, mais nettement plus lent (non mesuré ici) |
| Poste individuel | **RTX 3060 12 Go** | 12 Go | carte ~300–350 € · PC complet ~900–1 200 € *(estimation)* | Modèles 7–8B à l'aise |
| Poste confortable | **RTX 5060 Ti 16 Go** | 16 Go | carte ~450–600 € · PC complet ~1 100–1 500 € *(estimation)* | Modèles 7–14B |
| **Machine de test** | **RTX 3080 10 Go** | 10 Go | — | **Mesuré : ~13 s par question** (mistral 7B) |
| Petite équipe | **RTX 3090 24 Go** d'occasion | 24 Go | carte ~800–1 200 € d'occasion, très variable | Modèles 14–32B, plusieurs utilisateurs (avec un serveur adapté comme vLLM) |
| Alternative silencieuse | **Mac mini M4 Pro 48 Go** | 48 Go unifiée | ~2 900–3 200 € | Gros modèles, faible consommation (non testé ici) |

Au-delà (service pour toute une structure, dizaines d'utilisateurs) : serveur équipé de GPU professionnels, sur devis.

> **Prix relevés mi-novembre 2026** chez des revendeurs français. Le marché est tendu (pénurie de mémoire en 2026) : les prix varient fortement, à revérifier avant tout achat. Les prix de PC complets sont des estimations, pas des relevés.

**Point clé pour un service public ou de santé :** une fois les modèles téléchargés, la machine n'a plus besoin d'Internet. Elle peut fonctionner sur un réseau isolé.

## Utilisation

**1. Préparer Ollama** (une seule fois) :
```
ollama pull mistral
ollama pull nomic-embed-text
```
Puis lancer le serveur (l'application Ollama, ou `ollama serve`).

**2. Vérifier que tout est prêt :**
```
python rag_local.py check
```

**3. Déposer ses documents** dans `docs/` puis **indexer :**
```
python rag_local.py ingest
```

**4. Poser des questions :**
```
python rag_local.py ask "Quelle est la procédure en cas de rupture de stock ?"
```

## Exemple réel (RTX 3080, mistral 7B)

Sur le document d'exemple `docs/exemple-note-interne.md` (3 passages indexés) :

```
> python rag_local.py ask "Que faire en cas de rupture de stock ?"

En cas de rupture de stock, le responsable de rayon passe une commande d'urgence
au fournisseur référencé, signale l'indisponibilité par une étiquette
« temporairement indisponible », et note la rupture dans le cahier de suivi.

— Passages consultés (du plus au moins pertinent) —
  [1] exemple-note-interne.md : # Note interne — Procédures du rayon vrac …
  ...
```

Question dont la réponse **n'est pas** dans les documents :

```
> python rag_local.py ask "Quel est le salaire du responsable de rayon ?"

Dans le contexte fourni, aucun élément ne permet de déterminer le salaire
du responsable de rayon.
```

Le modèle reconnaît l'absence d'information au lieu d'inventer une réponse.

**Temps mesurés :** ~50 s pour la toute première question (chargement du modèle en mémoire GPU), puis **~13 s par question**.

### Réglages (variables d'environnement)
- `LLM_MODEL` — ex. `qwen2.5:7b`, `llama3.1:8b` (défaut : `mistral`)
- `EMBED_MODEL` — défaut : `nomic-embed-text`
- `OLLAMA_URL` — défaut : `http://localhost:11434`

## Limites (honnêtes)

- Démonstrateur, pas un produit : pas d'interface web, pas de gestion des droits, index reconstruit à chaque fois.
- La qualité des réponses dépend du modèle local et du découpage.
- **Constaté pendant les tests :** un modèle de 7B numérote mal ses références (il citait des passages inexistants, ou le mauvais). Les sources sont donc listées par le programme, à partir du classement de la recherche, qui lui est exact, et non par le modèle.
- Pour un vrai déploiement : base vectorielle dédiée (Chroma/Qdrant), modèle plus gros si le GPU le permet, et une évaluation des réponses.

## Pistes d'évolution

Interface web (chat), mise à jour incrémentale de l'index, modèle d'embeddings multilingue, conteneurisation pour déploiement sur un serveur interne, et une petite évaluation (jeu de questions/réponses de référence).

---

*Projet personnel — démonstrateur d'un RAG 100 % local pour montrer qu'on peut exploiter une IA utile sur des données sensibles sans dépendre du cloud.*
