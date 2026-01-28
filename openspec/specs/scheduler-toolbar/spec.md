## ADDED Requirements

### Requirement: Layout de la toolbar

La toolbar DOIT afficher les éléments de navigation et de sélection de vue.

#### Scenario: Structure de la toolbar
- **WHEN** la toolbar est affichée
- **THEN** elle contient à gauche : bouton "Aujourd'hui", boutons de navigation (précédent/suivant)
- **AND** elle contient au centre : le titre de la période (ex: "janv. – févr. 2026")
- **AND** elle contient à droite : un dropdown pour sélectionner la vue

---

### Requirement: Bouton Aujourd'hui

Le bouton "Aujourd'hui" DOIT permettre de revenir à la date du jour.

#### Scenario: Clic sur Aujourd'hui
- **WHEN** l'utilisateur clique sur "Aujourd'hui"
- **THEN** le calendrier navigue vers la date actuelle
- **AND** la vue reste inchangée

#### Scenario: Style du bouton
- **WHEN** le bouton "Aujourd'hui" est affiché
- **THEN** il a un style "pill" (bordure arrondie)
- **AND** il utilise les styles Cunningham

---

### Requirement: Navigation précédent/suivant

Les boutons de navigation DOIVENT permettre de naviguer dans le temps.

#### Scenario: Clic sur précédent
- **WHEN** l'utilisateur clique sur le bouton précédent (◀)
- **THEN** le calendrier navigue vers la période précédente

#### Scenario: Clic sur suivant
- **WHEN** l'utilisateur clique sur le bouton suivant (▶)
- **THEN** le calendrier navigue vers la période suivante

#### Scenario: Style des boutons de navigation
- **WHEN** les boutons de navigation sont affichés
- **THEN** ils sont des IconButtons avec flèches
- **AND** ils utilisent les styles Cunningham

---

### Requirement: Titre de la période

Le titre DOIT afficher la période actuellement visible.

#### Scenario: Affichage du titre
- **WHEN** la vue est en mode semaine ou jour
- **THEN** le titre affiche le mois et l'année (ex: "janv. – févr. 2026")

#### Scenario: Mise à jour du titre
- **WHEN** l'utilisateur navigue vers une autre période
- **THEN** le titre se met à jour pour refléter la nouvelle période

---

### Requirement: Sélecteur de vue

Le dropdown DOIT permettre de changer de vue via un menu déroulant custom.

#### Scenario: Options disponibles
- **WHEN** l'utilisateur clique sur le bouton trigger
- **THEN** un menu déroulant s'ouvre avec les options : Jour, Semaine, Mois, Liste
- **AND** l'option sélectionnée est mise en évidence avec un checkmark

#### Scenario: Changement de vue
- **WHEN** l'utilisateur sélectionne une vue différente
- **THEN** le calendrier change pour afficher cette vue
- **AND** le menu se ferme
- **AND** le bouton trigger affiche la vue sélectionnée

#### Scenario: Vue par défaut
- **WHEN** le calendrier est chargé
- **THEN** la vue "Semaine" est sélectionnée par défaut

#### Scenario: Fermeture du menu
- **WHEN** l'utilisateur clique en dehors du menu
- **THEN** le menu se ferme

---

### Requirement: Accessibilité clavier

Le sélecteur de vue DOIT être accessible au clavier.

#### Scenario: Navigation clavier
- **WHEN** le menu est ouvert
- **THEN** les touches ArrowUp/ArrowDown permettent de naviguer entre les options
- **AND** la touche Enter sélectionne l'option focalisée
- **AND** la touche Escape ferme le menu

#### Scenario: Focus visible
- **WHEN** une option est focalisée par le clavier
- **THEN** elle a un style visuel distinct (outline)

---

### Requirement: Synchronisation avec le calendrier

La toolbar DOIT rester synchronisée avec l'état du calendrier.

#### Scenario: Sync après navigation
- **WHEN** le calendrier change de période (via drag ou autre)
- **THEN** le titre de la toolbar se met à jour

#### Scenario: Sync après changement de vue externe
- **WHEN** la vue du calendrier change par un autre moyen
- **THEN** le dropdown affiche la vue correcte
