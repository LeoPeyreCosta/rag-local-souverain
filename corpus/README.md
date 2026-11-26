# Corpus d'évaluation

Huit documents internes d'une commune fictive (Saint-Clair-du-Lez) et des
questions d'agents annotées, pour mesurer deux choses : la recherche
retrouve-t-elle le passage qui contient la réponse, et le modèle répond-il
juste, ou dit-il qu'il ne sait pas quand l'information n'y est pas ?

## Données fictives

La commune, les procédures, les montants, les numéros de poste et les
adresses électroniques sont inventés ; les adresses utilisent le domaine
`.example`, réservé à la documentation. Les faits sont volontairement
précis et arbitraires (« bureau 104 », « 2,50 euros par jour ») : un modèle
ne peut pas les connaître sans lire les documents.

## Contenu

| Fichier | Rôle |
|---|---|
| `documents/` | 8 documents : accueil des nouveaux agents, frais de déplacement, télétravail, congés, sécurité informatique, accueil du public, protection des données, plan canicule |
| `developpement/questions.jsonl` | 40 questions (34 avec réponse, 6 sans) ayant servi à mettre au point l'outil |
| `controle/questions.jsonl` | questions écrites après le gel du code, évaluées telles quelles |
| `controle-2/questions.jsonl` | 27 questions (21 avec réponse, 6 sans) sur des faits qu'aucune autre question n'interroge, versées avant d'écrire la vérification des réponses par citation et avant toute mesure |

## Format d'une question

```json
{"id": "dev-07", "question": "Quel est le plafond de remboursement d'une nuit d'hôtel à Paris ?",
 "source": "02-frais-de-deplacement.md", "preuve": "110 euros à Paris", "mots_cles": [["110"]]}
```

- `preuve` : un morceau de phrase du document qui contient la réponse.
  La recherche est réussie si un des passages retenus le contient (sans
  tenir compte des accents, de la ponctuation ni des retours à la ligne).
  Une preuve courte tient toujours dans un passage, grâce au chevauchement
  de 80 caractères entre passages voisins. Une preuve introuvable dans
  l'index fait échouer l'évaluation.
- `mots_cles` : ce qu'une réponse juste doit contenir. Pour chaque groupe,
  au moins un mot commençant par l'un des termes, en minuscules et sans
  accents : `[["cinq", "5"]]` accepte « cinq jours » comme « 5 jours ». Le
  critère est sévère avec les reformulations inattendues.
- Une question sans réponse dans les documents a `source`, `preuve` et
  `mots_cles` à `null` : la seule réponse juste est la phrase de refus
  imposée par la consigne (« Je ne trouve pas cette information dans les
  documents. »).

Les questions reformulent les documents au lieu de les recopier (« Quel jour
du mois le salaire est-il versé ? » pour « La paie est versée le 27 de chaque
mois ») : c'est ce qui distingue une recherche par le sens d'une recherche
par mots.
