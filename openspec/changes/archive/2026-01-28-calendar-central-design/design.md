## Context

L'application utilise @event-calendar/core (vkurko/calendar), une bibliothèque Svelte qui expose des variables CSS `--ec-*` et des classes CSS `.ec-*` pour la personnalisation. Le design system Cunningham (@gouvfr-lasuite/cunningham-react) fournit les tokens visuels via des variables CSS `--c--globals--*`.

État actuel : le calendrier utilise les styles par défaut d'EventCalendar qui ne s'intègrent pas visuellement avec La Suite.

Contraintes :
- EventCalendar est une bibliothèque Svelte, pas React - on ne peut pas modifier ses composants internes
- La toolbar native ne supporte pas de dropdown React pour le sélecteur de vues
- Les variables CSS seules ne suffisent pas pour tous les aspects visuels

## Goals / Non-Goals

**Goals:**
- Aligner visuellement le calendrier central avec le design system Cunningham
- Créer une toolbar custom React avec navigation et sélecteur de vues
- Override les styles EventCalendar via variables CSS et classes CSS
- Supporter automatiquement le dark mode via les tokens Cunningham

**Non-Goals:**
- Différenciation visuelle des weekends (reporté)
- Redesign du mini-calendrier ou de la sidebar gauche
- Modification des modals d'événements
- Color picker pour les calendriers (futur)

## Decisions

### 1. Toolbar custom React vs Override CSS de la toolbar native

**Décision** : Toolbar custom React

**Alternatives considérées** :
- Override CSS des boutons natifs : limité pour le dropdown, moins de contrôle
- Modification du DOM via JavaScript : fragile, maintenance difficile

**Rationale** :
- Contrôle total sur le layout et les interactions
- Meilleure intégration avec le reste de l'app React
- Utilise les méthodes API d'EventCalendar (`prev()`, `next()`, `setOption()`, `getView()`)
- DropdownMenu custom (plutôt que Select Cunningham) pour une meilleure accessibilité clavier (Escape, Arrow, Enter)

### 2. Fichier de thème séparé vs Inline dans Scheduler.scss

**Décision** : Fichier `scheduler-theme.scss` séparé

**Rationale** :
- Séparation des responsabilités (thème vs composant)
- Facilite la maintenance et l'évolution du thème
- Permet de trouver facilement tous les overrides EventCalendar

### 3. Style "aujourd'hui" - Encadré vs Fond coloré

**Décision** : Encadré fin autour du numéro de jour, pas de fond

**Rationale** :
- Plus subtil et moderne
- Conforme à la maquette fournie
- Meilleure lisibilité (pas de conflit de couleurs)

### 4. Now indicator - Style existant vs Custom

**Décision** : Garder le style natif (ligne + point) avec couleur brand

**Rationale** :
- EventCalendar inclut déjà un cercle via `::before`
- Correspond à l'Option B identifiée (Google Calendar style)
- Seule la couleur nécessite un override

## Risks / Trade-offs

**[Couplage avec la structure DOM d'EventCalendar]**
→ Les sélecteurs CSS comme `.ec-col-head.ec-today time` dépendent de la structure HTML interne. Une mise à jour de la lib pourrait casser les styles. Mitigation : épingler la version et tester lors des mises à jour.

**[Synchronisation toolbar ↔ calendrier]**
→ La toolbar custom doit rester synchronisée avec l'état interne du calendrier (vue courante, dates). Mitigation : utiliser `getView()` et le callback `datesSet` pour maintenir la sync.

**[Performance des overrides CSS]**
→ Les sélecteurs imbriqués peuvent avoir un léger impact. Mitigation : sélecteurs simples, éviter les sélecteurs universels.
