# RAG local souverain

[![Tests](https://github.com/LeoPeyreCosta/rag-local-souverain/actions/workflows/tests.yml/badge.svg)](https://github.com/LeoPeyreCosta/rag-local-souverain/actions/workflows/tests.yml)

**Interroger ses documents internes avec un modèle de langue qui tourne
entièrement sur sa machine, depuis une page web ou en ligne de commande.**

Cas d'usage : un service (mairie, établissement de santé, cabinet, PME) veut
poser des questions en langage courant sur ses procédures internes, notes de
service et guides, **sans envoyer ces documents dans le cloud**. Le programme
retrouve les passages utiles (RAG : *retrieval-augmented generation*) et les
donne à un modèle local, qui rédige la réponse en s'appuyant sur eux
seulement.

## Exemple (réponses réelles)

Sur le corpus d'évaluation (huit documents internes d'une commune fictive),
avec mistral 7B et bge-m3 :

```text
Question : Combien de jours de télétravail par semaine pour un temps plein ?
Réponse  : Deux jours de télétravail par semaine pour un agent à temps plein.   (4,6 s)
Passages : 03-charte-teletravail.md (×4)

Question : Quel est le montant de la prime de Noël ?
Réponse  : Je ne trouve pas cette information dans les documents.               (4,5 s)
```

Dans la page web, la réponse s'écrit au fil de l'eau, suivie des passages
consultés (dépliables pour lire le texte exact) ; un refus est affiché comme
tel. La page liste aussi les documents, permet d'en ajouter et de mettre
l'index à jour.

![Page web : la question, la réponse, puis les passages consultés avec leur ressemblance à la question ; à droite, les documents et la mise à jour de l'index](captures/interface.png)

## Fonctionnement

```text
  Page web (HTML, CSS, JS sans bibliothèque)        Ligne de commande
        │  question                                        │
        ▼                                                  ▼
  API FastAPI (127.0.0.1:8000) ─────────────── rag_local ────────────────
        │
        ├─► vecteur de la question ──► Ollama (bge-m3)        [GPU local]
        │
        ├─► 4 passages les plus proches dans l'index (index.json, cosinus)
        │
        └─► consigne + passages + question ──► Ollama (mistral) [GPU local]
                                                     │
                     réponse en flux NDJSON : passages, texte, fin (refus ?)

  ── Tout le trafic reste sur la machine (localhost:11434 et 127.0.0.1:8000). ──
```

- **Index incrémental.** Chaque document est découpé en passages d'environ
  500 caractères qui se chevauchent. L'index garde l'empreinte de chaque
  document : une mise à jour ne recalcule que les documents nouveaux ou
  modifiés.
- **Les sources viennent de la recherche, pas du modèle.** Un modèle de 7
  milliards de paramètres numérote mal ses références ; le programme affiche
  donc lui-même les passages consultés, dans l'ordre de la recherche.
- **Un refus reconnaissable.** Quand les extraits ne contiennent pas la
  réponse, la consigne impose une phrase fixe (« Je ne trouve pas cette
  information dans les documents. »), que le code reconnaît, ainsi que ses
  reformulations courantes.

## Souveraineté : les garanties

- **Aucun appel externe.** Le programme ne parle qu'au serveur Ollama
  (`http://localhost:11434`), et la page ne charge aucune ressource
  extérieure (pas de police, de bibliothèque ni de statistique en ligne ;
  un test le vérifie).
- **Fonctionne hors ligne.** Une fois les modèles téléchargés, l'indexation
  et les questions n'ont pas besoin d'Internet. Pour le vérifier : couper le
  réseau et poser une question ; ou surveiller le trafic (pare-feu,
  Wireshark).
- **Accès local par défaut.** Le serveur web écoute sur `127.0.0.1` :
  seule la machine elle-même y accède. Il n'y a pas d'authentification ;
  l'ouvrir au réseau (`--hote 0.0.0.0`) donne accès aux documents à toute
  personne qui atteint la machine, et le programme le rappelle au démarrage.
- **Les données restent chez soi.** Documents, index et réponses ne sont
  écrits que sur le disque local ; le `.gitignore` exclut `docs/` et
  `index.json`, qui contient le texte des documents.

## Évaluation

Huit documents internes d'une commune fictive (accueil des agents, frais de
déplacement, télétravail, congés, sécurité informatique, accueil du public,
protection des données, plan canicule) et des questions d'agents annotées
(voir [`corpus/README.md`](corpus/README.md)). Pour chaque question, on
mesure :

- **la recherche** : le passage qui contient la réponse arrive-t-il en tête,
  ou au moins parmi les 4 passages donnés au modèle ?
- **la réponse** : juste, refus à tort (« je ne trouve pas » alors que
  l'information est là), ou fausse ; et pour les questions dont la réponse
  n'est **pas** dans les documents : refus correct, ou réponse inventée.

Deux jeux de questions : `developpement/` (40 questions, dont 6 sans
réponse) a servi à la mise au point ; `controle/` (21 questions, dont 5 sans
réponse) a été écrit et versé après le gel du code (commit `ca44386`), puis
mesuré sans correction ensuite. Chaque mesure a été faite deux fois, modèles
rechargés : résultats identiques.

### Recherche

| Embeddings | Développement : en tête | Développement : parmi les 4 | Contrôle : en tête | Contrôle : parmi les 4 |
|---|---|---|---|---|
| nomic-embed-text (version précédente) | 14/34 | 25/34 | 9/16 | 14/16 |
| **bge-m3 (retenu)** | 31/34 | **34/34** | 15/16 | **16/16** |

La version précédente de ce dépôt utilisait `nomic-embed-text`, entraîné
surtout sur de l'anglais : pour 9 questions de développement sur 34, le
passage utile n'était même pas transmis au modèle. `bge-m3`, multilingue,
le transmet à chaque fois.

### Réponses (mistral 7B)

| Embeddings | Questions avec réponse : justes | Refus à tort | Questions sans réponse : refus correct | Réponses inventées |
|---|---|---|---|---|
| nomic-embed-text, développement | 26/34 | 7 | 5/6 | 1 |
| nomic-embed-text, contrôle | 15/16 | 1 | 5/5 | 0 |
| **bge-m3, développement** | **34/34** | 0 | 5/6 | 1 |
| **bge-m3, contrôle** | **16/16** | 0 | 3/5 | 2 |

Environ 4,7 secondes par question (recherche et réponse) sur une RTX 3080.

Ce qu'il faut en retenir :

- **Avec bge-m3, toutes les réponses présentes dans les documents sont
  trouvées** (50 sur 50, les deux jeux réunis), contre 41 sur 50 avec
  nomic-embed-text, dont les échecs sont presque tous des « je ne trouve
  pas » honnêtes : le modèle n'avait pas reçu le bon passage.
- **Le revers : quand la réponse est absente, le modèle extrapole plus
  souvent.** Avec bge-m3, la recherche lui fournit des passages proches du
  sujet, et il en tire une conclusion que les documents ne donnent pas.
  Sur 11 questions sans réponse, 3 réponses inventées avec bge-m3, contre
  1 avec nomic-embed-text. Exemples réels :
  - « La mairie rembourse-t-elle l'abonnement de transport en commun des
    agents ? » → « Non, la mairie ne rembourse pas… » (les documents ne
    traitent que des frais de mission) ;
  - « Peut-on télétravailler depuis l'étranger ? » → « Non… selon la charte
    du télétravail » (la charte n'en parle pas).
- **bge-m3 est gardé par défaut** : manquer 9 réponses sur 50 qui sont dans
  les documents rend l'outil inutile pour l'agent. Mais une réponse
  affirmative ou négative doit se vérifier dans les passages affichés sous
  la réponse ; c'est pour cela qu'ils sont toujours montrés.

**Ce qui a changé pendant la mise au point.** La détection du refus ne
reconnaissait d'abord que la phrase imposée ; le modèle dit parfois la même
chose avec ses mots (« La cantine du personnel n'est pas mentionnée dans les
extraits »), ce qui était compté à tort comme une réponse inventée. Quelques
tournures précises sont maintenant reconnues ; un test vérifie qu'une simple
négation (« les amendes ne sont pas remboursées ») n'est pas prise pour un
refus. Une réponse du contrôle reste à la limite : « Non, il n'y a pas de
mention dans les extraits fournis que l'on puisse venir au travail avec son
chien » commence par une conclusion et est comptée comme inventée.

## Accessibilité

La page vise les règles d'accessibilité attendues d'un service public
(RGAA) :

- lien d'évitement vers la question, structure de titres sans saut,
  étiquette visible pour chaque champ, navigation complète au clavier et
  focus visible ;
- la réponse est annoncée aux lecteurs d'écran une fois complète, et non
  morceau par morceau pendant qu'elle s'écrit ;
- contrastes d'au moins 4,5:1 pour le texte et 3:1 pour les bordures, en
  thème clair comme en thème sombre (suivi des préférences du système) ;
  animations désactivées si l'utilisateur le demande.

Ces points sont contrôlés automatiquement
([`tests/test_accessibilite.py`](tests/test_accessibilite.py)). Ces contrôles
ne remplacent pas un audit : la page n'a pas été testée avec un lecteur
d'écran.

## Installation

Prérequis : Python 3.10 ou plus récent, [Ollama](https://ollama.com).

```sh
git clone https://github.com/LeoPeyreCosta/rag-local-souverain.git
cd rag-local-souverain
python -m pip install -e .
ollama pull mistral     # modèle de langue (4,4 Go)
ollama pull bge-m3      # embeddings multilingues (1,2 Go)
rag-local verifier
```

## Utilisation

```sh
# Interface web : http://127.0.0.1:8000
rag-local serveur

# En ligne de commande : déposer ses documents (.txt, .md, .pdf) dans docs/, puis
rag-local indexer
rag-local demander "Combien de jours de congés pour un mariage ?"

# Essayer sur le corpus d'exemple
rag-local serveur --documents corpus/documents

# Mesurer la recherche et les réponses
rag-local evaluer --questions corpus/controle/questions.jsonl --details
```

Réglages par variables d'environnement : `LLM_MODEL` (défaut `mistral`),
`EMBED_MODEL` (défaut `bge-m3`), `OLLAMA_URL`, `RAG_DOCUMENTS`, `RAG_INDEX`.
Changer de modèle d'embeddings impose de réindexer ; le programme le signale.

## Stack

| Élément | Choix | Pourquoi |
|---|---|---|
| Serveur de modèles | Ollama | local, simple, tourne sur la carte graphique |
| Modèle de langue | mistral 7B (quantifié) | bon en français, tient dans 10 Go de mémoire graphique |
| Embeddings | bge-m3 | multilingue ; voir l'évaluation |
| Recherche | Python pur (cosinus) | quelques milliers de passages : une base vectorielle n'apporte rien |
| API web | FastAPI, uvicorn | flux de réponse, dépôt de fichiers, peu de code |
| Page | HTML, CSS, JavaScript sans framework | rien à télécharger, rien à compiler, fonctionne hors ligne |
| Lecture PDF | pypdf | texte des PDF numériques |

## Quel matériel pour faire tourner ça ?

**La règle :** les modèles doivent tenir dans la mémoire de la carte
graphique. Ici, `mistral` 7B quantifié pèse environ 4,4 Go et `bge-m3`
1,2 Go : une carte de 8 Go devrait suffire pour un utilisateur (non testé).
Plus de mémoire permet des modèles plus gros ou plusieurs utilisateurs
simultanés.

| Usage | Matériel type | Mémoire | Prix indicatif | Ce que ça permet |
|---|---|---|---|---|
| Découverte | PC existant, sans carte graphique (16 Go de RAM) | — | 0 € | Fonctionne sur le processeur, mais nettement plus lent (non mesuré ici) |
| Poste individuel | RTX 3060 12 Go | 12 Go | carte ~300–350 € · PC complet ~900–1 200 € *(estimation)* | Modèles 7–8B à l'aise |
| Poste confortable | RTX 5060 Ti 16 Go | 16 Go | carte ~450–600 € · PC complet ~1 100–1 500 € *(estimation)* | Modèles 7–14B |
| **Machine de test** | **RTX 3080 10 Go** | 10 Go | — | **Mesuré : environ 4,7 s par question** (mistral 7B, réponses courtes) |
| Petite équipe | RTX 3090 24 Go d'occasion | 24 Go | carte ~800–1 200 € d'occasion, très variable | Modèles 14–32B, plusieurs utilisateurs (avec un serveur adapté comme vLLM) |
| Alternative silencieuse | Mac mini M4 Pro 48 Go | 48 Go unifiée | ~2 900–3 200 € | Gros modèles, faible consommation (non testé ici) |

Au-delà (service pour toute une structure, dizaines d'utilisateurs) :
serveur équipé de cartes professionnelles, sur devis.

> **Prix relevés mi-novembre 2026** chez des revendeurs français. Le marché
> est tendu (pénurie de mémoire en 2026) : les prix varient fortement, à
> revérifier avant tout achat. Les prix de PC complets sont des estimations,
> pas des relevés.

## Limites

- **Le modèle peut conclure au-delà des documents** (voir l'évaluation) :
  une réponse doit se vérifier dans les passages affichés.
- **Corpus d'évaluation petit et fictif** : 8 documents courts (34
  passages) et 61 questions, écrits par l'auteur. Sur une vraie base
  documentaire, plus grande et plus redondante, la recherche aura plus de
  passages proches à départager.
- **Un seul modèle de langue mesuré** (mistral 7B). Un modèle plus gros
  extrapolerait sans doute moins, au prix du temps et de la mémoire.
- **Pas d'authentification ni de droits par document** : outil local pour
  un poste, pas un service partagé.
- **PDF** : seul le texte numérique est lu ; un document scanné doit d'abord
  passer par une reconnaissance de caractères.
- **Accessibilité** contrôlée automatiquement, pas auditée (voir plus haut).

## Structure

```text
src/rag_local/
  config.py       réglages (variables d'environnement)
  documents.py    lecture des .txt, .md, .pdf et découpage en passages
  ollama.py       embeddings et réponse en flux via Ollama
  index.py        index incrémental, recherche par similarité cosinus
  reponse.py      consigne, refus reconnu, recherche puis réponse
  web.py          API FastAPI
  static/         page HTML, CSS, JavaScript
  evaluation.py   mesure de la recherche et des réponses
  __main__.py     ligne de commande rag-local
tests/            tests unitaires, API et accessibilité (sans GPU ni Ollama)
corpus/           documents fictifs, questions annotées, guide
docs/             vos documents (non versionnés)
```

## Tests

```sh
python -m pip install -e ".[dev]"
python -m pytest
```

Les tests remplacent Ollama par un faux client : ils tournent sans GPU ni
réseau, et dans la CI sur Python 3.10 à 3.13.

## Licence

MIT
