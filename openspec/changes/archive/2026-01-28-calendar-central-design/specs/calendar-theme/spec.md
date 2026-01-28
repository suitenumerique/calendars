## ADDED Requirements

### Requirement: Variables CSS Cunningham

Le thème DOIT remapper les variables CSS d'EventCalendar (`--ec-*`) vers les tokens Cunningham (`--c--globals--*`).

#### Scenario: Couleurs de base appliquées
- **WHEN** le calendrier est rendu
- **THEN** le fond utilise `--c--globals--colors--gray-000`
- **AND** les bordures utilisent `--c--globals--colors--gray-100`
- **AND** le texte utilise `--c--globals--colors--gray-800`

#### Scenario: Dark mode automatique
- **WHEN** le système est en dark mode
- **THEN** les couleurs s'adaptent automatiquement via les tokens Cunningham

---

### Requirement: Style du jour actuel

Le jour actuel DOIT être affiché avec un encadré fin autour du numéro, sans fond coloré.

#### Scenario: Header du jour actuel
- **WHEN** un jour est le jour actuel
- **THEN** le numéro du jour est entouré d'une bordure fine (1px)
- **AND** la bordure a un border-radius de 4px
- **AND** le fond de la colonne header reste transparent

---

### Requirement: Style des événements

Les événements DOIVENT avoir un style épuré avec coins arrondis.

#### Scenario: Apparence d'un événement
- **WHEN** un événement est affiché dans la grille
- **THEN** il a un border-radius de 6px
- **AND** il n'a pas de box-shadow
- **AND** le titre est en font-weight 600 (semi-bold)
- **AND** l'horaire est en font-weight 400 avec légère opacité

#### Scenario: Couleur d'un événement
- **WHEN** un événement appartient à un calendrier
- **THEN** il prend la couleur de ce calendrier en fond
- **AND** le texte est blanc

---

### Requirement: Style du now indicator

L'indicateur de l'heure actuelle DOIT utiliser la couleur brand.

#### Scenario: Apparence du now indicator
- **WHEN** l'heure actuelle est visible dans la vue
- **THEN** une ligne horizontale avec un point est affichée
- **AND** la couleur est `--c--globals--colors--brand-500`

---

### Requirement: Style de la sidebar heures

La sidebar affichant les heures DOIT avoir un style discret.

#### Scenario: Apparence des labels d'heure
- **WHEN** la sidebar des heures est affichée
- **THEN** la font-size est réduite (0.75rem)
- **AND** la couleur est `--c--globals--colors--gray-500`

---

### Requirement: Toolbar native masquée

La toolbar native d'EventCalendar DOIT être masquée.

#### Scenario: Toolbar native invisible
- **WHEN** le calendrier est rendu
- **THEN** l'élément `.ec-toolbar` a `display: none`

---

### Requirement: Lignes de grille simplifiées

Les lignes de grille DOIVENT afficher uniquement les heures pleines.

#### Scenario: Pas de lignes intermédiaires
- **WHEN** la vue semaine ou jour est affichée
- **THEN** seules les lignes horaires (chaque heure) sont visibles
- **AND** les lignes intermédiaires (30 min) sont masquées

---

### Requirement: Header unifié

Le header (en-têtes de colonnes + section all-day) DOIT avoir un aspect unifié.

#### Scenario: Pas de bordures internes
- **WHEN** le header est affiché
- **THEN** les éléments `.ec-col-head` et `.ec-all-day` n'ont pas de bordures
- **AND** les `.ec-day` dans `.ec-all-day` n'ont pas de bordure droite

#### Scenario: Sidebar header masquée
- **WHEN** le header est affiché
- **THEN** le texte du timezone dans `.ec-sidebar` du header est invisible

---

### Requirement: Bordure de grille

La grille du body DOIT avoir une bordure en bas et à droite.

#### Scenario: Bordures de la grille
- **WHEN** la grille du calendrier est affichée
- **THEN** `.ec-grid` dans `.ec-body` a une bordure bottom et right
