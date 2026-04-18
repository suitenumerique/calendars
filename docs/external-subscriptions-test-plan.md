# Plan de test manuel — Import de calendriers externes

## Prérequis

- `make start` (tous les services up)
- `sync_all_subscriptions` et `cleanup_orphan_subscriptions` sont déclenchés par cron externe (voir docs de déploiement)
- Être connecté sur http://localhost:8930
- Avoir au moins un calendrier personnel existant
- Avoir une URL ICS publique valide pour tester (ex: jours fériés français : `https://calendrier.api.gouv.fr/jours-feries/metropole.ics`, ou un calendrier Google public)

---

## 1. Ajout d'un abonnement

### 1.1 Ouverture de la modale
- [ ] Dans le panneau gauche, vérifier qu'une section **"Abonnements"** (ou "Subscriptions") apparaît sous les calendriers personnels
- [ ] Cliquer sur le bouton `+` à côté du titre de la section
- [ ] La modale "Ajouter un abonnement" s'ouvre

### 1.2 Validation du formulaire
- [ ] Soumettre sans URL → erreur de validation
- [ ] Entrer une URL invalide (ex: `pas-une-url`) → soumettre → erreur du serveur affichée
- [ ] Entrer une URL HTTP (pas HTTPS, ex: `http://example.com/cal.ics`) → erreur

#### Protection SSRF
- [ ] `https://localhost/cal.ics` → rejet (hôte privé)
- [ ] `https://127.0.0.1/cal.ics` → rejet
- [ ] `https://[::1]/cal.ics` → rejet
- [ ] `https://10.0.0.1/cal.ics` (RFC1918) → rejet
- [ ] `https://192.168.1.1/cal.ics` (RFC1918) → rejet
- [ ] `https://172.16.0.1/cal.ics` (RFC1918) → rejet
- [ ] Hôte public qui résout vers une IP privée → rejet
- [ ] URL dont la chaîne de redirection 3xx aboutit à une adresse privée ou locale → rejet au hop concerné

### 1.3 Ajout réussi
- [ ] Entrer une URL ICS valide (HTTPS)
- [ ] Optionnel : saisir un nom d'affichage
- [ ] Optionnel : choisir une couleur
- [ ] Cliquer "S'abonner" → spinner de chargement visible
- [ ] La modale se ferme
- [ ] Le calendrier apparaît dans la section "Abonnements"
- [ ] Les événements du calendrier externe s'affichent dans le scheduler

---

## 2. Affichage read-only des événements

### 2.1 Clic sur un événement d'abonnement
- [ ] Cliquer sur un événement provenant d'un calendrier abonné
- [ ] La modale **read-only** s'ouvre (pas le formulaire d'édition)
- [ ] Vérifier l'affichage : titre, date/heure, lieu (si présent), description (si présente)
- [ ] Vérifier que les participants sont listés avec leur statut (accepted, declined, etc.)
- [ ] Vérifier qu'il n'y a **aucun bouton d'édition** ni de suppression

### 2.2 Drag & drop bloqué
- [ ] Essayer de drag-and-drop un événement d'abonnement → l'événement revient à sa position d'origine
- [ ] Essayer de resize un événement d'abonnement → l'événement revient à sa taille d'origine

### 2.3 Événements réguliers non impactés
- [ ] Cliquer sur un événement d'un calendrier personnel → le formulaire d'édition normal s'ouvre
- [ ] Drag & drop sur un événement personnel → fonctionne normalement
- [ ] Créer un nouvel événement → le calendrier abonné n'apparaît PAS dans la liste des calendriers disponibles

---

## 3. Gestion des abonnements

### 3.1 Édition
- [ ] Cliquer sur le menu d'un calendrier abonné → option "Modifier"
- [ ] Changer le nom → Sauvegarder → le nom est mis à jour dans la liste
- [ ] Changer la couleur → Sauvegarder → la couleur est mise à jour (événements aussi)
- [ ] Changer l'URL source → Sauvegarder → les anciens événements sont remplacés par les nouveaux

### 3.2 Suppression
- [ ] Cliquer sur le menu d'un calendrier abonné → option "Supprimer"
- [ ] Le calendrier disparaît de la liste
- [ ] Les événements associés disparaissent du scheduler

### 3.3 Toggle visibilité
- [ ] Décocher un calendrier abonné dans la liste → ses événements disparaissent du scheduler
- [ ] Re-cocher → les événements réapparaissent

---

## 4. Status badge & synchronisation

### 4.1 État normal
- [ ] Après un ajout réussi, pas de badge visible (état "ok")

### 4.2 État erreur (nécessite une URL qui va échouer)
- [ ] Créer un abonnement avec une URL qui marche
- [ ] Modifier l'URL vers une URL invalide (ex: `https://example.com/not-a-calendar`)
- [ ] Attendre quelques minutes (ou forcer via l'API)
- [ ] Un badge d'erreur (icône warning) apparaît
- [ ] Cliquer dessus → le détail de l'erreur s'affiche

### 4.3 État stoppé & réactivation
- [ ] Après 3 erreurs consécutives, le badge passe en "stoppé" (icône block)
- [ ] Le détail affiche un message explicatif + bouton "Réactiver"
- [ ] Corriger l'URL (modifier vers une URL valide)
- [ ] Cliquer "Réactiver" → le statut repasse en "pending" puis "ok"

---

## 5. Limites

### 5.1 Limite d'abonnements (20 par défaut)
- [ ] Si on a déjà 20 abonnements, le bouton `+` est désactivé ou un message "Limite atteinte" s'affiche

---

## 6. Section repliable

- [ ] Cliquer sur le header "Abonnements" → la section se replie (les calendriers sont masqués)
- [ ] Re-cliquer → la section se déplie
- [ ] Quand la section est repliée, les événements restent visibles dans le scheduler (seul l'affichage de la liste est impacté)

---

## 7. Internationalisation

- [ ] Changer la langue en FR → toutes les chaînes de la feature sont en français
- [ ] Changer en EN → toutes les chaînes sont en anglais
- [ ] Changer en NL → toutes les chaînes sont en néerlandais (pas de clés brutes visibles)
