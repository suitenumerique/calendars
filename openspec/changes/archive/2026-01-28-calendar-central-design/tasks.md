## 1. Setup fichiers de thème

- [x] 1.1 Créer le fichier `scheduler-theme.scss` dans `src/frontend/apps/calendars/src/features/calendar/components/scheduler/`
- [x] 1.2 Ajouter l'import de `scheduler-theme.scss` dans `globals.scss`

## 2. Variables CSS et overrides de base

- [x] 2.1 Définir les variables CSS `--ec-*` mappées vers les tokens Cunningham
- [x] 2.2 Ajouter le style `.ec-toolbar { display: none }` pour masquer la toolbar native

## 3. Style du jour actuel

- [x] 3.1 Override `.ec-col-head.ec-today` pour fond transparent
- [x] 3.2 Ajouter le style encadré sur `.ec-col-head.ec-today time`

## 4. Style des événements

- [x] 4.1 Override `.ec-event` : border-radius 6px, box-shadow none, padding ajusté
- [x] 4.2 Override `.ec-event-title` : font-weight 600
- [x] 4.3 Override `.ec-event-time` : font-weight 400, opacity 0.95

## 5. Style du now indicator et sidebar

- [x] 5.1 Override couleur du now indicator vers brand-500
- [x] 5.2 Override `.ec-sidebar` : font-size 0.75rem, couleur gray-500

## 6. Composant SchedulerToolbar

- [x] 6.1 Créer le fichier `SchedulerToolbar.tsx`
- [x] 6.2 Créer le fichier `SchedulerToolbar.scss`
- [x] 6.3 Implémenter le bouton "Aujourd'hui" avec appel à `setOption('date', new Date())`
- [x] 6.4 Implémenter les boutons de navigation avec appels à `prev()` et `next()`
- [x] 6.5 Implémenter le titre dynamique de la période avec `getView()`
- [x] 6.6 Implémenter le dropdown des vues avec `setOption('view', ...)`

## 7. Intégration

- [x] 7.1 Modifier `useSchedulerInit.ts` : ajouter `headerToolbar: false`
- [x] 7.2 Modifier `Scheduler.tsx` : intégrer `<SchedulerToolbar />` au-dessus du container
- [x] 7.3 Passer la ref du calendrier à la toolbar pour accéder aux méthodes API

## 8. Synchronisation toolbar ↔ calendrier

- [x] 8.1 Utiliser le callback `datesSet` pour mettre à jour le titre de la toolbar
- [x] 8.2 Synchroniser le dropdown avec la vue courante

## 9. Améliorations post-implémentation

- [x] 9.1 Supprimer les lignes intermédiaires (30 min) de la grille
- [x] 9.2 Unifier le header (ec-col-head + ec-all-day) sans bordures internes
- [x] 9.3 Masquer le texte timezone dans ec-sidebar du header
- [x] 9.4 Ajouter bordure bottom/right à ec-grid
- [x] 9.5 Remplacer Select par DropdownMenu custom pour le sélecteur de vue
- [x] 9.6 Ajouter navigation clavier au dropdown (Escape, Arrow, Enter)
- [x] 9.7 Ajouter les traductions calendar.navigation.previous/next (EN, FR, NL)
- [x] 9.8 Corriger le type CalendarApi dans CalendarContext
- [x] 9.9 Mémoiser les handlers avec useCallback

## 10. Vérification

- [x] 10.1 Vérifier le rendu visuel sur les 4 vues (Jour, Semaine, Mois, Liste)
- [x] 10.2 Vérifier la navigation et le changement de vue
