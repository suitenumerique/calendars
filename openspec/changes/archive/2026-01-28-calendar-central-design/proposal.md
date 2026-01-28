## Why

L'application calendrier n'a actuellement aucun design établi. Le composant EventCalendar utilise les styles par défaut de la bibliothèque @event-calendar/core qui ne correspondent pas à l'identité visuelle de La Suite (design system Cunningham). Cette première itération vise à créer un design épuré et moderne pour le calendrier central.

## What Changes

- Création d'une toolbar custom React remplaçant la toolbar native d'EventCalendar
- Override des variables CSS `--ec-*` pour utiliser les tokens Cunningham
- Override des classes CSS pour personnaliser les événements, headers de jours, sidebar
- Style "aujourd'hui" avec encadré fin (sans fond coloré)
- Événements avec coins arrondis, sans ombre, titre en gras
- Now indicator avec couleur brand
- Sidebar heures avec style discret

## Capabilities

### New Capabilities

- `calendar-theme`: Thème visuel du calendrier central aligné sur le design system Cunningham. Couvre les variables CSS, les overrides de classes, et les styles des événements.
- `scheduler-toolbar`: Toolbar custom React pour la navigation et le changement de vue du calendrier. Remplace la toolbar native d'EventCalendar.

### Modified Capabilities

_(Aucune capability existante modifiée)_

## Impact

- **Frontend** : Nouveaux fichiers SCSS et composants React dans `src/frontend/apps/calendars/src/features/calendar/components/scheduler/`
- **Fichiers modifiés** :
  - `useSchedulerInit.ts` : désactivation de la toolbar native (`headerToolbar: false`)
  - `Scheduler.tsx` : intégration de la toolbar custom
  - `globals.scss` : import du nouveau fichier de thème
- **Dépendances** : Utilise les composants Cunningham existants (Button, Select)
- **API EventCalendar** : Utilise les méthodes `prev()`, `next()`, `setOption()`, `getView()`
