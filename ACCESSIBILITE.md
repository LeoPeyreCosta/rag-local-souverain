# Accessibilité de la page web

Ce document dit ce qui a été vérifié sur la page web du RAG, comment, et ce
qui ne l'a pas été. **Ce n'est pas un audit RGAA** : un audit porte sur
l'ensemble des critères, il est mené par une personne formée, avec des
lecteurs d'écran ; il n'a pas eu lieu. Il n'y a donc pas de déclaration de
conformité.

Dernière vérification : 27 novembre 2026, Microsoft Edge, axe-core 4.10.

## En bref

- 17 vérifications faites dans un vrai navigateur par
  [`outils/audit_accessibilite.py`](outils/audit_accessibilite.py) : toutes
  réussies.
- La version précédente de la page n'en réussissait que 9. Pourtant axe-core
  n'y relevait aucune violation : les défauts étaient dans les parcours
  (erreurs de saisie, serveur injoignable, noms de boutons identiques), qu'un
  outil automatique ne parcourt pas.
- Les contrastes de toutes les couleurs de la page sont calculés par les
  tests unitaires, en thème clair et en thème sombre.
- Pas encore vérifié : l'usage réel avec un lecteur d'écran, le mode de
  contraste élevé de Windows, le validateur HTML du W3C, le zoom du texte
  seul à 200 %.

## Comment c'est vérifié

**Tests unitaires** ([`tests/test_accessibilite.py`](tests/test_accessibilite.py),
lancés à chaque envoi sur GitHub) : langue et titre de la page, titres sans
saut de niveau, une étiquette par champ, références ARIA existantes,
messages d'erreur écrits par la page, champ obligatoire signalé, aucune
ressource externe, aucune insertion de HTML par le script, et les
contrastes (4,5:1 pour le texte, 3:1 pour les bordures et le focus).

**Vérification dans le navigateur**
([`outils/audit_accessibilite.py`](outils/audit_accessibilite.py), à lancer
à la main : il faut Ollama, Edge et axe-core). Le script pilote la page comme
un utilisateur au clavier et contrôle :

| Vérification | Ce qui est contrôlé |
|---|---|
| axe-core (4 fois) | règles WCAG 2.0 à 2.2, niveaux A et AA, et bonnes pratiques ; thème clair et sombre, avant et après une réponse |
| Ordre de tabulation | lien d'évitement, question, Envoyer, fichiers, Ajouter, Mettre à jour l'index |
| Focus visible | contour d'au moins 2 px sur chaque élément atteint au clavier |
| Lien d'évitement | visible quand il a le focus ; Entrée place le focus dans la question |
| Annonce de la réponse | une fois écrite, avec la phrase qui l'appuie ou l'avertissement « non vérifiée » |
| Boutons « Lire le passage » | quatre noms distincts ; Entrée déplie le passage |
| Question vide | message sous le champ, champ marqué invalide et relié au message, focus conservé ; le message disparaît à la saisie |
| Dépôt sans fichier | même traitement |
| Après un dépôt | le champ fichier est vidé |
| Serveur injoignable | message à la place de la réponse, annoncé ; le bouton redevient utilisable |
| 320 px de large | aucun défilement horizontal, avec un nom de fichier de 98 caractères sans tiret |
| Espacement du texte | interlignage, espacement des lettres, des mots et des paragraphes agrandis (critère 10.12) : rien ne déborde ni n'est coupé |

Le script enregistre aussi l'arbre d'accessibilité de la page (ce que reçoit
un lecteur d'écran) et des captures, pour relecture. Il ne modifie rien sur
le serveur : le dépôt de fichier et la panne sont simulés dans le navigateur.

```bash
pip install -e ".[audit]"
npm install axe-core
rag-local serveur --documents corpus/documents --port 8791    # index à jour
python outils/audit_accessibilite.py http://127.0.0.1:8791 --axe node_modules/axe-core/axe.min.js
```

## Ce que la vérification a trouvé, et les corrections

| Défaut | Conséquence | Correction |
|---|---|---|
| Serveur injoignable pendant une question | le message « Failed to fetch » s'affichait dans le panneau Documents ; la réponse restait bloquée sur « Recherche dans les documents… » ; rien n'était annoncé | message en français à la place de la réponse, annoncé |
| Les quatre boutons s'appelaient « Lire le passage » | au lecteur d'écran, dans la liste des boutons, impossible de savoir lequel ouvre quoi | « Lire le passage 2 », suivi du nom du document pour les lecteurs d'écran |
| Question vide | bulle du navigateur, qui disparaît au bout de quelques secondes ; une question faite d'espaces ne produisait rien du tout | message écrit sous le champ, relié au champ (`aria-describedby`), champ marqué invalide (`aria-invalid`), message annoncé |
| Dépôt sans fichier choisi | rien ne se passait | même traitement |
| Limite de 20 Mo et PDF scannés | non indiqués avant l'envoi | texte d'aide sous le champ, relié au champ |
| Annonce de la réponse | la phrase d'appui était collée à ce qui précède (« réponse) :Le télétravail… ») | phrase entre guillemets |
| Progression | « Recherche dans les documents… » n'était pas annoncé | annoncé une fois au début |
| Nom de fichier long sans tiret | débordement horizontal à 320 px | le texte passe à la ligne |

## Critères du RGAA 4.1.2 examinés

Seuls les critères qui s'appliquent à cette page et qui ont été regardés
figurent ici. « Vérifié » veut dire : contrôlé par les moyens indiqués, sans
défaut trouvé ; pas : déclaré conforme.

| Critère | Ce qui a été regardé | Moyen | Résultat |
|---|---|---|---|
| 1 (images), 2 (cadres), 4 (multimédia), 5 (tableaux) | la page n'en contient pas | lecture du code | sans objet |
| 3.1 Information pas seulement par la couleur | refus, erreurs, documents non indexés, phrase surlignée : chacun a aussi un texte (la phrase surlignée est recopiée en toutes lettres sous la réponse) | lecture du code | vérifié |
| 3.2 Contraste du texte | chaque couleur de texte sur chaque fond, clair et sombre ; texte principal 16,9:1 (clair) et 15,6:1 (sombre) | tests unitaires | vérifié |
| 3.3 Contraste des composants | bordures des champs 3,7:1 et 4,9:1, contour de focus 7,1:1 et 8,7:1 | tests unitaires | vérifié |
| 6.1 Liens explicites | un seul lien, « Aller à la question » | lecture du code | vérifié |
| 7.1 Scripts compatibles avec les technologies d'assistance | composants natifs (boutons, `details`, champ fichier) ; noms et rôles dans l'arbre d'accessibilité | script, arbre relu | vérifié dans l'arbre ; **pas essayé avec un lecteur d'écran** |
| 7.3 Scripts utilisables au clavier | question, dépliage des passages, dépôt, index | script | vérifié |
| 7.4 Changement de contexte | aucun rechargement ; le focus ne bouge que sur une erreur de saisie, après l'action de l'utilisateur | lecture du code | vérifié |
| 7.5 Messages de statut | état du serveur et message des documents en `role="status"` ; progression, réponse et erreurs dans une zone `aria-live` | script, lecture du code | vérifié dans le DOM ; **pas essayé avec un lecteur d'écran** |
| 8.1, 8.3, 8.5, 8.6 Type de document, langue, titre | `<!doctype html>`, `lang="fr"`, titre « RAG local : interroger vos documents » | tests unitaires, axe-core | vérifié |
| 8.2 Code valide | HTML court, écrit à la main | — | **non vérifié** (validateur du W3C non passé) |
| 9.1 Titres | un seul `h1`, aucun niveau sauté | tests unitaires | vérifié |
| 9.2 Structure | en-tête, contenu principal, panneau des documents (`header`, `main`, `aside`) | axe-core, arbre | vérifié |
| 9.3 Listes | passages en liste numérotée (classés), documents en liste simple | arbre | vérifié |
| 9.4 Citations | passages et phrase d'appui en `blockquote` | arbre | vérifié |
| 10.4 Texte agrandi à 200 % | tailles en `rem` ; l'essai à 320 px (soit un zoom de 400 % sur 1 280 px) ne perd rien | indirect | **non vérifié** directement (zoom du texte seul) |
| 10.7 Focus visible | contour de 3 px sur chaque élément du parcours | script | vérifié |
| 10.11 Lecture à 320 px | aucun défilement horizontal | script | vérifié |
| 10.12 Espacement du texte | rien ne déborde ni n'est coupé | script | vérifié |
| 10.13 Contenus au survol ou au focus | pas d'infobulle ; le lien d'évitement devient visible quand il reçoit lui-même le focus | lecture du code | sans objet |
| 11.1, 11.2 Étiquettes | chaque champ a une étiquette visible, reliée, explicite | tests unitaires, arbre | vérifié |
| 11.9 Intitulés des boutons | Envoyer, Ajouter, Mettre à jour l'index, Lire le passage 1 à 4 | arbre | vérifié |
| 11.10 Contrôle de saisie | champ obligatoire signalé (« obligatoire » et `required`) ; formats et taille indiqués avant l'envoi ; erreurs écrites sous le champ et reliées | script | vérifié |
| 11.11 Suggestions de correction | « Saisissez une question avant d'envoyer », « Choisissez au moins un fichier à ajouter » ; fichier refusé par le serveur : motif donné (format, taille) | script, lecture du code | vérifié |
| 12.7 Lien d'évitement | présent, premier élément atteint au clavier | script | vérifié |
| 12.8 Ordre de tabulation | cohérent avec l'ordre de lecture | script | vérifié |
| 12.9 Pas de piège au clavier | la tabulation fait le tour de la page et revient au début | script | vérifié |
| 13 (consultation) | pas de limite de temps, pas d'animation, pas de document à télécharger | lecture du code | sans objet |

## Ce qui reste à faire

**Essai avec un lecteur d'écran** (NVDA, gratuit, avec Firefox ou Edge ; ou
le Narrateur de Windows). Le parcours à suivre, environ dix minutes :

1. Ouvrir la page : le titre de la page et l'état du serveur sont lus.
2. Touche Tab : « Aller à la question » ; Entrée : on arrive dans le champ
   « Votre question (obligatoire) », avec son aide.
3. Entrée sans rien écrire : « Saisissez une question avant d'envoyer » est
   lu.
4. Écrire une question, Entrée : « Recherche dans les documents… » puis,
   une seule fois, la réponse et la phrase qui l'appuie.
5. Naviguer par boutons : « Lire le passage 1 (…) » à « Lire le passage 4
   (…) », l'état replié ou déplié est lu.
6. Naviguer par titres et par régions : en-tête, « Poser une question »,
   « Réponse », « Passages consultés », « Documents ».
7. Panneau Documents : « Ajouter » sans fichier, puis « Mettre à jour
   l'index » : les messages sont lus.

Résultat : pas encore fait.

**Contraste élevé de Windows** (couleurs forcées) : l'émulation du
navigateur n'applique pas les couleurs du système ; à essayer sur un poste
réglé ainsi, en particulier le surlignage et l'état des boutons occupés.

**Validateur HTML du W3C** et **zoom du texte seul à 200 %** (Firefox,
Affichage, Zoom texte seulement).

**Des utilisateurs** : aucune personne utilisant un lecteur d'écran, une
loupe ou la commande vocale n'a essayé la page.
