// Page du RAG local. Aucune bibliothèque : fetch, flux NDJSON et DOM.
// Tout texte venu du serveur (réponse, passages, noms de fichiers) est inséré
// avec textContent, jamais innerHTML : un document ne peut pas injecter de code.
"use strict";

const element = (id) => document.getElementById(id);

function bouton(b, occupe) {
  b.setAttribute("aria-disabled", occupe ? "true" : "false");
  b.dataset.occupe = occupe ? "1" : "";
}

async function erreurHttp(reponse) {
  try {
    const corps = await reponse.json();
    return corps.detail || `Erreur ${reponse.status}`;
  } catch {
    return `Erreur ${reponse.status}`;
  }
}

// fetch lève une TypeError quand le serveur ne répond pas du tout.
function messageErreur(erreur) {
  return erreur instanceof TypeError
    ? "Le serveur ne répond pas : vérifiez qu'il est lancé, puis réessayez."
    : `Erreur : ${erreur.message}`;
}

// Une seule zone d'annonce pour les lecteurs d'écran (aria-live="polite"). On la
// vide avant d'écrire, pour qu'un message identique soit annoncé de nouveau.
function annoncer(texte) {
  const zone = element("annonce");
  zone.textContent = "";
  setTimeout(() => {
    zone.textContent = texte;
  }, 100);
}

// Erreur de saisie : message visible sous le champ, relié au champ
// (aria-describedby, aria-invalid), et annoncé. Il disparaît quand la saisie change.
function signalerErreur(champ, zone, message) {
  zone.textContent = message;
  zone.hidden = false;
  champ.setAttribute("aria-invalid", "true");
  const decrit = (champ.getAttribute("aria-describedby") || "").split(" ").filter(Boolean);
  if (!decrit.includes(zone.id)) champ.setAttribute("aria-describedby", [...decrit, zone.id].join(" "));
  // Le focus sur le champ fait lire son nom et le message ; s'il y est déjà, on annonce.
  if (document.activeElement === champ) annoncer(message);
  else champ.focus();
}

function effacerErreur(champ, zone) {
  if (zone.hidden) return;
  zone.hidden = true;
  zone.textContent = "";
  champ.removeAttribute("aria-invalid");
  const decrit = (champ.getAttribute("aria-describedby") || "").split(" ").filter((id) => id && id !== zone.id);
  champ.setAttribute("aria-describedby", decrit.join(" "));
}

// ------------------------------------------------------------------- état
async function chargerEtat() {
  const etat = element("etat");
  try {
    const reponse = await fetch("/api/etat");
    const donnees = await reponse.json();
    const morceaux = [];
    morceaux.push(donnees.ollama ? `Ollama : ${donnees.modele_llm}` : "Ollama injoignable : lancez « ollama serve »");
    morceaux.push(
      donnees.index
        ? `index : ${donnees.index.passages} passages (${donnees.index.modele_embeddings})`
        : "aucun index"
    );
    etat.textContent = morceaux.join(" · ");
    etat.classList.toggle("probleme", !donnees.ollama || !donnees.index);
    afficherDocuments(donnees.documents);
  } catch {
    etat.textContent = "Le serveur ne répond pas.";
    etat.classList.add("probleme");
  }
}

function afficherDocuments(documents) {
  const liste = element("documents");
  liste.replaceChildren();
  if (!documents.length) {
    const li = document.createElement("li");
    li.textContent = "Aucun document pour l'instant.";
    liste.append(li);
    return;
  }
  for (const doc of documents) {
    const li = document.createElement("li");
    li.textContent = doc.nom;
    if (!doc.indexe) {
      li.classList.add("non-indexe");
      li.append(" (pas encore indexé)");
    }
    liste.append(li);
  }
}

// --------------------------------------------------------------- question
let passagesAffiches = [];

function afficherSources(passages) {
  passagesAffiches = passages;
  const liste = element("sources");
  liste.replaceChildren();
  for (const [i, passage] of passages.entries()) {
    const li = document.createElement("li");
    const titre = document.createElement("p");
    const nom = document.createElement("strong");
    nom.textContent = passage.source;
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = ` — ressemblance ${passage.score.toFixed(2).replace(".", ",")}`;
    titre.append(nom, score);
    const details = document.createElement("details");
    // « Lire le passage 2 (charte.md) » : un nom distinct pour chaque bouton, la
    // source n'étant lue que par les lecteurs d'écran (elle est affichée juste au-dessus).
    const resume = document.createElement("summary");
    const source = document.createElement("span");
    source.className = "visuellement-masque";
    source.textContent = ` (${passage.source})`;
    resume.append(`Lire le passage ${i + 1}`, source);
    const citation = document.createElement("blockquote");
    citation.textContent = passage.texte;
    details.append(resume, citation);
    li.append(titre, details);
    liste.append(li);
  }
}

// Les positions viennent de Python : elles comptent des caractères Unicode,
// pas des unités UTF-16 comme les chaînes JavaScript, d'où Array.from.
function morceau(texte, debut, fin) {
  return Array.from(texte).slice(debut, fin).join("");
}

function afficherAppui(evenement) {
  const zone = element("appui");
  zone.replaceChildren();
  zone.hidden = false;
  if (!evenement.trouve) {
    zone.className = "appui non-appuyee";
    zone.textContent =
      "Réponse non vérifiée : aucune phrase des passages n'a pu lui être rattachée. " +
      "Lisez les passages avant de vous en servir.";
    return;
  }
  const passage = passagesAffiches[evenement.rang - 1];
  const cite = morceau(passage.texte, evenement.debut, evenement.fin);
  zone.className = "appui";
  const intro = document.createElement("p");
  intro.textContent = `Phrase qui appuie la réponse (passage ${evenement.rang}, ${passage.source}) :`;
  const citation = document.createElement("blockquote");
  citation.textContent = cite;
  zone.append(intro, citation);

  // Dans la liste des passages : surligner la phrase et déplier le passage.
  const li = element("sources").children[evenement.rang - 1];
  const marque = document.createElement("mark");
  marque.textContent = cite;
  li.querySelector("blockquote").replaceChildren(
    morceau(passage.texte, 0, evenement.debut),
    marque,
    morceau(passage.texte, evenement.fin),
  );
  li.querySelector("details").open = true;
}

// L'appui tel qu'il sera annoncé : « Phrase qui appuie la réponse (…) : « … » ».
function texteAppui() {
  const zone = element("appui");
  if (zone.hidden) return "";
  const intro = zone.querySelector("p");
  const citation = zone.querySelector("blockquote");
  return intro && citation ? `${intro.textContent} « ${citation.textContent} »` : zone.textContent;
}

// L'erreur s'affiche à la place de la réponse, pas ailleurs dans la page.
function erreurReponse(message) {
  const reponse = element("reponse");
  reponse.textContent = message;
  reponse.className = "reponse erreur";
  element("duree").textContent = "";
  annoncer(message);
}

async function poser(question) {
  const reponse = element("reponse");
  element("zone-reponse").hidden = false;
  reponse.textContent = "";
  reponse.className = "reponse";
  element("appui").hidden = true;
  element("appui").replaceChildren();
  element("duree").textContent = "Recherche dans les documents…";
  element("sources").replaceChildren();
  annoncer("Recherche dans les documents…");

  try {
    await lireReponse(question);
  } catch (erreur) {
    erreurReponse(messageErreur(erreur));
  }
}

async function lireReponse(question) {
  const resultat = await fetch("/api/question", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!resultat.ok) {
    erreurReponse(await erreurHttp(resultat));
    return;
  }

  const lecteur = resultat.body.getReader();
  const decodeur = new TextDecoder();
  let tampon = "";
  for (;;) {
    const { value, done } = await lecteur.read();
    if (done) break;
    tampon += decodeur.decode(value, { stream: true });
    const lignes = tampon.split("\n");
    tampon = lignes.pop();
    for (const ligne of lignes) {
      if (ligne.trim()) traiter(JSON.parse(ligne));
    }
  }
}

function traiter(evenement) {
  const reponse = element("reponse");
  switch (evenement.type) {
    case "sources":
      afficherSources(evenement.passages);
      element("duree").textContent = "Rédaction de la réponse…";
      break;
    case "texte":
      // Le modèle commence souvent par une espace, visible avec white-space: pre-wrap.
      reponse.textContent += reponse.textContent ? evenement.contenu : evenement.contenu.trimStart();
      break;
    case "verification":
      element("duree").textContent = "Recherche de la phrase qui appuie la réponse…";
      break;
    case "appui":
      afficherAppui(evenement);
      break;
    case "fin": {
      if (evenement.refus) reponse.classList.add("refus");
      element("duree").textContent = `Réponse en ${String(evenement.duree_s).replace(".", ",")} s.`;
      annoncer(`Réponse : ${reponse.textContent} ${texteAppui()}`.trim());
      break;
    }
    case "erreur":
      erreurReponse(`Erreur : ${evenement.message}`);
      break;
  }
}

// -------------------------------------------------------------- documents
async function deposer(fichiers) {
  const message = element("message-documents");
  const donnees = new FormData();
  for (const fichier of fichiers) donnees.append("fichiers", fichier);
  message.textContent = "Envoi…";
  const reponse = await fetch("/api/documents", { method: "POST", body: donnees });
  if (!reponse.ok) {
    message.textContent = await erreurHttp(reponse);
    return;
  }
  const resultat = await reponse.json();
  const morceaux = [];
  if (resultat.enregistres.length) {
    morceaux.push(`Ajouté : ${resultat.enregistres.join(", ")}. Mettez l'index à jour pour les interroger.`);
  }
  for (const refus of resultat.refuses) morceaux.push(`Refusé : ${refus.nom} (${refus.motif}).`);
  message.textContent = morceaux.join(" ");
  element("fichiers").value = "";
  await chargerEtat();
}

async function indexer() {
  const message = element("message-documents");
  message.textContent = "Mise à jour de l'index…";
  const reponse = await fetch("/api/indexer", { method: "POST" });
  if (!reponse.ok) {
    message.textContent = await erreurHttp(reponse);
    return;
  }
  const bilan = await reponse.json();
  message.textContent =
    `Index à jour : ${bilan.documents} documents, ${bilan.passages} passages ` +
    `(${bilan.recalcules.length} recalculés, ${bilan.reutilises.length} inchangés).`;
  await chargerEtat();
}

// -------------------------------------------------------------- démarrage
// Un bouton occupé ignore les nouveaux clics ; l'erreur éventuelle s'affiche
// près de l'action qui l'a causée (siErreur).
function occuper(bouton_, action, siErreur) {
  return async (...args) => {
    if (bouton_.dataset.occupe) return;
    bouton(bouton_, true);
    try {
      await action(...args);
    } catch (erreur) {
      siErreur(messageErreur(erreur));
    } finally {
      bouton(bouton_, false);
    }
  };
}

document.addEventListener("DOMContentLoaded", () => {
  const champ = element("question");
  const erreurQuestion = element("erreur-question");
  const lancer = occuper(element("envoyer"), poser, erreurReponse);

  element("formulaire-question").addEventListener("submit", (evenement) => {
    evenement.preventDefault();
    const question = champ.value.trim();
    if (!question) {
      signalerErreur(champ, erreurQuestion, "Saisissez une question avant d'envoyer.");
      return;
    }
    effacerErreur(champ, erreurQuestion);
    lancer(question);
  });
  champ.addEventListener("input", () => effacerErreur(champ, erreurQuestion));
  champ.addEventListener("keydown", (evenement) => {
    if (evenement.key === "Enter" && !evenement.shiftKey && !evenement.isComposing) {
      evenement.preventDefault();
      element("formulaire-question").requestSubmit();
    }
  });

  const fichiers = element("fichiers");
  const erreurFichiers = element("erreur-fichiers");
  const messageDocuments = (texte) => {
    element("message-documents").textContent = texte;
  };
  const ajouter = occuper(element("formulaire-depot").querySelector("button"), deposer, messageDocuments);
  element("formulaire-depot").addEventListener("submit", (evenement) => {
    evenement.preventDefault();
    if (!fichiers.files.length) {
      signalerErreur(fichiers, erreurFichiers, "Choisissez au moins un fichier à ajouter.");
      return;
    }
    effacerErreur(fichiers, erreurFichiers);
    ajouter(fichiers.files);
  });
  fichiers.addEventListener("change", () => effacerErreur(fichiers, erreurFichiers));
  const boutonIndex = element("indexer");
  boutonIndex.addEventListener("click", occuper(boutonIndex, indexer, messageDocuments));

  chargerEtat();
});
