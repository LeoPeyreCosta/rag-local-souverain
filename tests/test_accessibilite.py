"""Contrôles automatiques d'accessibilité de la page.

Ils ne remplacent pas un audit RGAA (navigation au lecteur d'écran, zoom,
parcours complet) : ils empêchent de casser ce qui est déjà en place.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

STATIQUE = Path(__file__).resolve().parents[1] / "src" / "rag_local" / "static"


class Analyse(HTMLParser):
    def __init__(self):
        super().__init__()
        self.balises: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.balises.append((tag, dict(attrs)))


@pytest.fixture(scope="module")
def page() -> list[tuple[str, dict]]:
    analyse = Analyse()
    analyse.feed((STATIQUE / "index.html").read_text(encoding="utf-8"))
    return analyse.balises


def test_langue_titre_et_titres_hierarchises(page):
    assert ("html", {"lang": "fr"}) in page
    niveaux = [int(tag[1]) for tag, _ in page if re.fullmatch(r"h[1-6]", tag)]
    assert niveaux.count(1) == 1 and niveaux[0] == 1
    assert all(b - a <= 1 for a, b in zip(niveaux, niveaux[1:])), "un niveau de titre est sauté"


def test_chaque_champ_a_une_etiquette(page):
    etiquettes = {attrs["for"] for tag, attrs in page if tag == "label"}
    champs = [attrs for tag, attrs in page if tag in ("input", "textarea", "select")]
    assert champs and all(c.get("id") in etiquettes for c in champs)


def test_lien_d_evitement_et_annonces(page):
    identifiants = {attrs.get("id") for _, attrs in page}
    evitement = next(attrs for tag, attrs in page if tag == "a" and "evitement" in attrs.get("class", ""))
    assert evitement["href"].lstrip("#") in identifiants
    assert any(attrs.get("aria-live") == "polite" for _, attrs in page)
    assert any(attrs.get("role") == "status" for _, attrs in page)


def test_references_aria_existent(page):
    """aria-describedby et aria-labelledby ne pointent que vers des éléments présents."""
    identifiants = {attrs.get("id") for _, attrs in page}
    for _, attrs in page:
        for cle in ("aria-describedby", "aria-labelledby"):
            for cible in attrs.get(cle, "").split():
                assert cible in identifiants, f"{cle}={cible}"


def test_erreurs_de_saisie_ecrites_par_la_page(page):
    """La page affiche ses propres messages d'erreur, reliés au champ par le script,
    plutôt que la bulle du navigateur qui disparaît au bout de quelques secondes."""
    script = (STATIQUE / "app.js").read_text(encoding="utf-8")
    formulaires = [attrs for tag, attrs in page if tag == "form"]
    assert formulaires and all("novalidate" in attrs for attrs in formulaires)
    zones = [attrs for _, attrs in page if "erreur-champ" in (attrs.get("class") or "")]
    assert {z["id"] for z in zones} == {"erreur-question", "erreur-fichiers"}
    for zone in zones:
        assert "hidden" in zone
        assert f'element("{zone["id"]}")' in script
    assert 'setAttribute("aria-invalid", "true")' in script


def test_champ_obligatoire_signale(page):
    question = next(attrs for tag, attrs in page if tag == "textarea")
    assert "required" in question
    texte = (STATIQUE / "index.html").read_text(encoding="utf-8")
    assert "Votre question (obligatoire)" in texte


def test_aucune_ressource_externe(page):
    """La page fonctionne hors ligne : rien n'est chargé depuis Internet."""
    for _, attrs in page:
        for cle in ("src", "href"):
            assert not attrs.get(cle, "").startswith(("http:", "https:", "//")), attrs


def test_aucune_insertion_html_dans_le_script():
    script = (STATIQUE / "app.js").read_text(encoding="utf-8")
    code = re.sub(r"//.*", "", script)  # les commentaires peuvent nommer innerHTML
    assert "innerHTML" not in code and "insertAdjacentHTML" not in code


# -------------------------------------------------------------- contrastes
def _couleurs(bloc: str) -> dict[str, str]:
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", bloc))


def _luminance(hexa: str) -> float:
    canaux = [int(hexa[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lineaires = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in canaux]
    return 0.2126 * lineaires[0] + 0.7152 * lineaires[1] + 0.0722 * lineaires[2]


def contraste(a: str, b: str) -> float:
    clair, sombre = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (clair + 0.05) / (sombre + 0.05)


feuille = (STATIQUE / "style.css").read_text(encoding="utf-8")
CLAIR = _couleurs(feuille.split("@media (prefers-color-scheme: dark)")[0])
SOMBRE = {**CLAIR, **_couleurs(feuille.split("@media (prefers-color-scheme: dark)")[1].split("}")[0])}

# (premier plan, arrière-plan, contraste minimal) : 4,5 pour le texte, 3 pour les bordures.
PAIRES = [
    ("texte", "fond", 4.5),
    ("texte", "surface", 4.5),
    ("texte-secondaire", "fond", 4.5),
    ("texte-secondaire", "surface", 4.5),
    ("accent", "fond", 4.5),
    ("texte-sur-accent", "accent", 4.5),
    ("erreur", "fond", 4.5),
    ("erreur", "surface", 4.5),
    ("alerte", "fond", 4.5),
    ("alerte", "surface", 4.5),
    ("texte", "surligne", 4.5),
    ("focus", "fond", 3.0),
    ("bordure", "fond", 3.0),
]


@pytest.mark.parametrize("theme, couleurs", [("clair", CLAIR), ("sombre", SOMBRE)])
@pytest.mark.parametrize("avant, arriere, minimum", PAIRES)
def test_contrastes(theme, couleurs, avant, arriere, minimum):
    ratio = contraste(couleurs[avant], couleurs[arriere])
    assert ratio >= minimum, f"{theme} : {avant} sur {arriere} = {ratio:.2f}:1"
