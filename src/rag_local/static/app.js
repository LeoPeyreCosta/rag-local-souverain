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
function afficherSources(passages) {
  const liste = element("sources");
  liste.replaceChildren();
  for (const passage of passages) {
    const li = document.createElement("li");
    const titre = document.createElement("p");
    const nom = document.createElement("strong");
    nom.textContent = passage.source;
    const score = document.createElement("span");
    score.className = "score";
    score.textContent = ` — ressemblance ${passage.score.toFixed(2)}`;
    titre.append(nom, score);
    const details = document.createElement("details");
    const resume = document.createElement("summary");
    resume.textContent = "Lire le passage";
    const citation = document.createElement("blockquote");
    citation.textContent = passage.texte;
    details.append(resume, citation);
    li.append(titre, details);
    liste.append(li);
  }
}

async function poser(question) {
  const zone = element("zone-reponse");
  const reponse = element("reponse");
  const annonce = element("annonce");
  zone.hidden = false;
  reponse.textContent = "";
  reponse.className = "reponse";
  element("duree").textContent = "Recherche dans les documents…";
  element("sources").replaceChildren();
  annonce.textContent = "";

  const resultat = await fetch("/api/question", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!resultat.ok) {
    reponse.textContent = await erreurHttp(resultat);
    reponse.classList.add("erreur");
    element("duree").textContent = "";
    annonce.textContent = reponse.textContent;
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
    case "fin":
      if (evenement.refus) reponse.classList.add("refus");
      element("duree").textContent = `Réponse en ${String(evenement.duree_s).replace(".", ",")} s.`;
      element("annonce").textContent = `Réponse : ${reponse.textContent}`;
      break;
    case "erreur":
      reponse.textContent = `Erreur : ${evenement.message}`;
      reponse.classList.add("erreur");
      element("duree").textContent = "";
      element("annonce").textContent = reponse.textContent;
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
function occuper(bouton_, action) {
  return async (...args) => {
    if (bouton_.dataset.occupe) return;
    bouton(bouton_, true);
    try {
      await action(...args);
    } catch (erreur) {
      element("message-documents").textContent = `Erreur : ${erreur.message}`;
    } finally {
      bouton(bouton_, false);
    }
  };
}

document.addEventListener("DOMContentLoaded", () => {
  const champ = element("question");
  const envoyer = element("envoyer");
  const lancer = occuper(envoyer, poser);

  element("formulaire-question").addEventListener("submit", (evenement) => {
    evenement.preventDefault();
    const question = champ.value.trim();
    if (question) lancer(question);
  });
  champ.addEventListener("keydown", (evenement) => {
    if (evenement.key === "Enter" && !evenement.shiftKey && !evenement.isComposing) {
      evenement.preventDefault();
      element("formulaire-question").requestSubmit();
    }
  });

  const ajouter = element("formulaire-depot").querySelector("button");
  element("formulaire-depot").addEventListener("submit", (evenement) => {
    evenement.preventDefault();
    const fichiers = element("fichiers").files;
    if (fichiers.length) occuper(ajouter, deposer)(fichiers);
  });
  const boutonIndex = element("indexer");
  boutonIndex.addEventListener("click", occuper(boutonIndex, indexer));

  chargerEtat();
});
