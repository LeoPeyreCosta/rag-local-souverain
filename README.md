# RAG local souverain

**Interroger ses documents privés avec un LLM qui tourne entièrement sur sa propre machine — sans qu'aucune donnée ne quitte le réseau local.**

Cas d'usage : un service (santé, administration, cabinet, PME) veut poser des questions en langage naturel sur ses documents internes — notes, procédures, dossiers — **sans envoyer ces données dans le cloud**. C'est l'approche « IA souveraine » : confidentialité par conception, utilisable même sur un réseau isolé (*air-gapped*).

---

## Ce que ça fait

On dépose des documents dans `docs/` (`.txt`, `.md`, `.pdf`). Le programme les découpe, les transforme en vecteurs (*embeddings*) **en local**, et les range dans un index. Quand on pose une question, il retrouve les passages les plus pertinents et les donne à un LLM **local** qui rédige la réponse en citant ses sources.

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
  Réponse + sources citées

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

### Réglages (variables d'environnement)
- `LLM_MODEL` — ex. `qwen2.5:7b`, `llama3.1:8b` (défaut : `mistral`)
- `EMBED_MODEL` — défaut : `nomic-embed-text`
- `OLLAMA_URL` — défaut : `http://localhost:11434`

## Limites (honnêtes)

- Démonstrateur, pas un produit : pas d'interface web, pas de gestion des droits, index reconstruit à chaque fois.
- La qualité des réponses dépend du modèle local et du découpage.
- Pour un vrai déploiement : base vectorielle dédiée (Chroma/Qdrant), modèle plus gros si le GPU le permet, et une évaluation des réponses.

## Pistes d'évolution

Interface web (chat), mise à jour incrémentale de l'index, modèle d'embeddings multilingue, conteneurisation pour déploiement sur un serveur interne, et une petite évaluation (jeu de questions/réponses de référence).

---

*Projet personnel — démonstrateur d'un RAG 100 % local pour montrer qu'on peut exploiter une IA utile sur des données sensibles sans dépendre du cloud.*
