"""Vérification d'accessibilité de la page web, dans un vrai navigateur.

Ce que fait ce script (méthode et résultats : ACCESSIBILITE.md) :

- axe-core, règles WCAG 2.0 à 2.2 (niveaux A et AA) et bonnes pratiques, en
  thème clair et en thème sombre, avant et après une réponse ;
- parcours au clavier seul : ordre de tabulation, focus visible, lien
  d'évitement, question envoyée avec Entrée, passage déplié avec Entrée ;
- arbre d'accessibilité de la page (ce que reçoit un lecteur d'écran),
  enregistré pour être relu ;
- erreurs : question vide, dépôt sans fichier, serveur injoignable ;
- 320 px de large, puis espacement du texte agrandi : aucun débordement.

Il ne remplace ni un audit RGAA ni un essai avec un lecteur d'écran.

Le script ne modifie rien côté serveur : le dépôt de fichier et la panne du
serveur sont simulés dans le navigateur. Il pose une vraie question, donc
Ollama doit tourner et l'index exister.

Prérequis :
    pip install -e ".[audit]"     Playwright ; Microsoft Edge installé, ou
                                  « playwright install chromium » et --chromium
    npm install axe-core          fournit node_modules/axe-core/axe.min.js

Usage :
    rag-local serveur --documents corpus/documents --port 8791   (index à jour)
    python outils/audit_accessibilite.py http://127.0.0.1:8791 --axe node_modules/axe-core/axe.min.js
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import FilePayload, Page, Route, sync_playwright
from playwright.sync_api import TimeoutError as DelaiDepasse

QUESTION = "Combien de jours de télétravail par semaine pour un agent à temps plein ?"
# Des tirets bas : le navigateur ne peut pas couper le nom (il coupe après un tiret).
NOM_LONG = "compte_rendu_du_comite_de_direction_elargi_du_douze_novembre_deux_mille_vingt_six_version_relue.md"
ORDRE_ATTENDU = ["a.evitement", "textarea#question", "button#envoyer", "input#fichiers", "button", "button#indexer"]

AXE_RUN = """async () => {
  const r = await axe.run(document, {
    runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']},
    resultTypes: ['violations', 'incomplete']});
  const f = x => ({id: x.id, impact: x.impact, aide: x.help,
                   noeuds: x.nodes.map(n => ({cible: n.target.join(' '), resume: n.failureSummary}))});
  return {violations: r.violations.map(f), a_verifier: r.incomplete.map(f), reussies: r.passes.map(x => x.id)};
}"""

FOCUS = """() => { const e = document.activeElement; const cs = getComputedStyle(e);
  const r = e.getBoundingClientRect();
  return {selecteur: e.tagName.toLowerCase() + (e.id ? '#' + e.id : (e.className ? '.' + e.className : '')),
          contour_visible: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) >= 2,
          dans_la_fenetre: r.width > 0 && r.height > 0 && r.top >= 0 && r.bottom <= innerHeight}; }"""

DEBORDEMENTS = """(largeur) => [...document.querySelectorAll('body *')]
  .filter(e => { const r = e.getBoundingClientRect();
    return r.width && (r.right > largeur + 1 || r.left < -1) && !e.closest('.visuellement-masque, .evitement'); })
  .map(e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : ''))"""

COUPES = """() => [...document.querySelectorAll('body *')]
  .filter(e => { const cs = getComputedStyle(e);
    return (cs.overflow === 'hidden' || cs.overflowY === 'hidden') && e.scrollHeight > e.clientHeight + 1
           && !e.closest('.visuellement-masque'); })
  .map(e => e.tagName.toLowerCase() + (e.id ? '#' + e.id : ''))"""

ETAT_CHAMP = """([id, erreur]) => { const c = document.getElementById(id); const z = document.getElementById(erreur);
  return {focus: document.activeElement.id, invalide: c.getAttribute('aria-invalid') === 'true',
          relie: (c.getAttribute('aria-describedby') || '').split(' ').includes(erreur),
          message: z && !z.hidden ? z.textContent : ''}; }"""

ESPACEMENT = (
    "* { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; }"
    " p { margin-bottom: 2em !important; }"
)


class Audit:
    def __init__(self, url: str, axe: str, sortie: Path):
        self.url, self.axe, self.sortie = url, axe, sortie
        self.constats: list[tuple[bool, str, str]] = []
        self.details: dict = {}

    def constater(self, ok: bool, quoi: str, detail: object = "") -> None:
        self.constats.append((bool(ok), quoi, "" if ok else json.dumps(detail, ensure_ascii=False)[:600]))

    # ---------------------------------------------------------------- outils
    def ouvrir(self, page: Page) -> None:
        page.goto(self.url)
        page.wait_for_function("document.getElementById('etat').textContent.includes('index')")
        if "aucun index" in page.inner_text("#etat"):
            sys.exit("Aucun index : mettez-le à jour depuis la page avant l'audit.")

    def poser(self, page: Page) -> None:
        page.fill("#question", QUESTION)
        page.press("#question", "Enter")
        self.attendre_reponse(page)

    @staticmethod
    def attendre(page: Page, condition: str, delai: int = 5_000) -> bool:
        """Faux si la condition n'est pas remplie à temps : le constat qui suit échouera."""
        try:
            page.wait_for_function(condition, timeout=delai)
            return True
        except DelaiDepasse:
            return False

    @staticmethod
    def attendre_reponse(page: Page) -> None:
        page.wait_for_function(
            "document.getElementById('duree').textContent.startsWith('Réponse en')", timeout=120_000
        )

    def axe_core(self, page: Page, etat: str) -> None:
        if not page.evaluate("typeof axe !== 'undefined'"):
            page.evaluate(self.axe)
        resultat = page.evaluate(AXE_RUN)
        self.details[f"axe {etat}"] = resultat
        self.constater(not resultat["violations"], f"axe-core, {etat} : aucune violation", resultat["violations"])

    @staticmethod
    def simuler_document_long(page: Page) -> None:
        """Le serveur « renvoie » un document au nom très long, sans rien écrire."""

        def etat(route: Route) -> None:
            reponse = route.fetch()
            donnees = reponse.json()
            donnees["documents"].append({"nom": NOM_LONG, "indexe": False})
            route.fulfill(response=reponse, json=donnees)

        page.route("**/api/etat", etat)
        page.route(
            "**/api/documents",
            lambda route: route.fulfill(json={"enregistres": [NOM_LONG], "refuses": []}),
        )

    # ------------------------------------------------------------- parcours
    def clavier_et_erreurs(self, page: Page) -> None:
        self.ouvrir(page)
        suite = []
        for _ in range(len(ORDRE_ATTENDU)):
            page.keyboard.press("Tab")
            suite.append(page.evaluate(FOCUS))
        self.details["ordre de tabulation"] = suite
        self.constater(
            [f["selecteur"] for f in suite] == ORDRE_ATTENDU,
            "ordre de tabulation : évitement, question, Envoyer, fichiers, Ajouter, index",
            suite,
        )
        self.constater(all(f["contour_visible"] for f in suite), "focus visible sur chaque élément", suite)
        self.axe_core(page, "accueil, thème clair")

        # Lien d'évitement : visible à la prise de focus, Entrée mène à la question.
        self.ouvrir(page)
        page.keyboard.press("Tab")
        evitement = page.evaluate(FOCUS)
        page.screenshot(path=self.sortie / "lien-evitement.png", clip={"x": 0, "y": 0, "width": 700, "height": 160})
        page.keyboard.press("Enter")
        self.constater(
            evitement["dans_la_fenetre"] and page.evaluate("document.activeElement.id") == "question",
            "lien d'évitement visible au focus, Entrée place le focus dans la question",
            evitement,
        )

        # Question tapée et envoyée au clavier ; la réponse est annoncée une fois complète.
        page.keyboard.type(QUESTION)
        page.keyboard.press("Enter")
        self.attendre_reponse(page)
        self.attendre(page, "document.getElementById('annonce').textContent.startsWith('Réponse :')")
        annonce = page.evaluate("document.getElementById('annonce').textContent")
        self.details["annonce de la réponse"] = annonce
        self.constater(
            "« " in annonce or "non vérifiée" in annonce,
            "réponse annoncée avec sa phrase d'appui (ou l'avertissement « non vérifiée »)",
            annonce,
        )
        self.axe_core(page, "après une réponse, thème clair")
        for zone in ("header", "main", "aside"):
            (self.sortie / f"arbre-{zone}.yaml").write_text(page.locator(zone).aria_snapshot(), encoding="utf-8")

        noms = page.evaluate("[...document.querySelectorAll('#sources summary')].map(s => s.textContent)")
        self.constater(len(set(noms)) == len(noms) == 4, "les 4 boutons « Lire le passage » ont des noms distincts", noms)
        page.focus("#sources li:nth-child(2) summary")
        page.keyboard.press("Enter")
        self.constater(
            page.evaluate("document.querySelector('#sources li:nth-child(2) details').open"),
            "Entrée sur « Lire le passage 2 » le déplie",
        )

        # Question vide : message sous le champ, relié, annoncé ; il disparaît à la saisie.
        page.fill("#question", "   ")
        page.press("#question", "Enter")
        self.attendre(page, "document.getElementById('annonce').textContent.startsWith('Saisissez')")
        vide = page.evaluate(ETAT_CHAMP, ["question", "erreur-question"])
        page.screenshot(path=self.sortie / "erreur-question.png", clip={"x": 0, "y": 140, "width": 900, "height": 300})
        self.constater(
            vide["focus"] == "question" and vide["invalide"] and vide["relie"] and vide["message"],
            "question vide : message visible, champ marqué invalide et relié au message, focus conservé",
            vide,
        )
        page.keyboard.type("x")
        apres = page.evaluate(ETAT_CHAMP, ["question", "erreur-question"])
        self.constater(not (apres["invalide"] or apres["relie"] or apres["message"]), "le message disparaît à la saisie", apres)

        # Dépôt sans fichier, puis dépôt simulé d'un fichier au nom très long.
        page.click("#formulaire-depot button")
        sans = page.evaluate(ETAT_CHAMP, ["fichiers", "erreur-fichiers"])
        self.constater(
            sans["focus"] == "fichiers" and sans["invalide"] and sans["relie"] and sans["message"],
            "dépôt sans fichier : message visible, relié au champ, focus sur le champ",
            sans,
        )
        self.simuler_document_long(page)
        fichier: FilePayload = {"name": NOM_LONG, "mimeType": "text/markdown", "buffer": b"# Essai"}
        page.set_input_files("#fichiers", files=[fichier])
        page.click("#formulaire-depot button")
        self.attendre(page, "document.getElementById('message-documents').textContent.startsWith('Ajouté')")
        self.constater(
            page.evaluate("document.getElementById('fichiers').files.length === 0"),
            "après un dépôt, le champ fichier est vidé",
        )

        # Serveur injoignable : l'erreur remplace la réponse et elle est annoncée.
        page.route("**/api/question", lambda route: route.abort())
        page.fill("#question", QUESTION)
        page.press("#question", "Enter")
        self.attendre(page, "document.getElementById('reponse').classList.contains('erreur')")
        self.attendre(page, "document.getElementById('annonce').textContent.startsWith('Le serveur')")
        coupe = {
            "reponse": page.inner_text("#reponse"),
            "progression": page.inner_text("#duree"),
            "bouton": page.get_attribute("#envoyer", "aria-disabled") or "",
        }
        self.constater(
            coupe["reponse"].startswith("Le serveur ne répond pas") and not coupe["progression"]
            and coupe["bouton"] == "false",
            "serveur injoignable : message à la place de la réponse, annoncé, bouton de nouveau utilisable",
            coupe,
        )

    def theme_sombre(self, page: Page) -> None:
        self.ouvrir(page)
        self.axe_core(page, "accueil, thème sombre")
        self.poser(page)
        self.axe_core(page, "après une réponse, thème sombre")

    def largeur_320(self, page: Page) -> None:
        self.simuler_document_long(page)
        self.ouvrir(page)
        self.poser(page)
        largeur = page.evaluate("document.documentElement.scrollWidth")
        trop = page.evaluate(DEBORDEMENTS, 320)
        self.constater(largeur <= 320 and not trop, "320 px de large : aucun défilement horizontal", [largeur, trop])
        page.screenshot(path=self.sortie / "largeur-320.png", full_page=True)
        page.add_style_tag(content=ESPACEMENT)
        # Un texte qui dépasse de sa boîte n'agrandit que la largeur du document.
        largeur = page.evaluate("document.documentElement.scrollWidth")
        trop, coupes = page.evaluate(DEBORDEMENTS, 320), page.evaluate(COUPES)
        self.constater(
            largeur <= 320 and not trop and not coupes,
            "espacement du texte agrandi : rien ne déborde ni n'est coupé",
            [largeur, trop, coupes],
        )

    def lancer(self, chromium: bool) -> int:
        self.sortie.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            navigateur = p.chromium.launch(channel=None if chromium else "msedge", headless=True)
            reglages: dict = {"locale": "fr-FR", "viewport": {"width": 1280, "height": 900}}
            for parcours, theme, largeur in (
                (self.clavier_et_erreurs, "light", 1280),
                (self.theme_sombre, "dark", 1280),
                (self.largeur_320, "light", 320),
            ):
                contexte = navigateur.new_context(
                    **{**reglages, "color_scheme": theme, "viewport": {"width": largeur, "height": 900}}
                )
                parcours(contexte.new_page())
                contexte.close()
            navigateur.close()

        (self.sortie / "details.json").write_text(
            json.dumps(self.details, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for ok, quoi, detail in self.constats:
            print(("ok     " if ok else "ÉCHEC  ") + quoi + (f"\n       {detail}" if detail else ""))
        a_verifier = sorted({v["id"] for cle, r in self.details.items() if cle.startswith("axe") for v in r["a_verifier"]})
        if a_verifier:
            print(f"axe-core, à vérifier à la main : {', '.join(a_verifier)} (détail dans {self.sortie / 'details.json'})")
        echecs = sum(not ok for ok, _, _ in self.constats)
        print(f"\n{len(self.constats) - echecs}/{len(self.constats)} vérifications réussies ; "
              f"captures et arbre d'accessibilité dans {self.sortie}")
        return 1 if echecs else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("url", help="adresse du serveur, par exemple http://127.0.0.1:8791")
    parser.add_argument("--axe", required=True, help="chemin de axe.min.js (paquet npm axe-core)")
    parser.add_argument("--sortie", default="rapport-accessibilite", help="dossier des captures et du détail")
    parser.add_argument("--chromium", action="store_true", help="Chromium de Playwright au lieu d'Edge")
    args = parser.parse_args()
    axe = Path(args.axe).read_text(encoding="utf-8")
    sys.exit(Audit(args.url.rstrip("/"), axe, Path(args.sortie)).lancer(args.chromium))


if __name__ == "__main__":
    main()
