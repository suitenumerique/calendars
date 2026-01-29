## Why

Le scheduler affiche les événements avec un décalage d'une heure par rapport à l'heure réelle. La cause : une double application de l'offset timezone lors de la conversion des dates ICS vers l'affichage. Le pattern "fake UTC" utilisé pour communiquer avec ts-ics fuit dans le chemin d'affichage, où `local.date` (fake UTC) est lu avec `getHours()` (qui ajoute l'offset navigateur), créant un décalage de ±N heures selon la timezone. Ce bug corrompt aussi les données lors de drag & drop, car l'utilisateur corrige visuellement des positions déjà décalées.

## What Changes

- Corriger `icsDateToJsDate()` pour retourner le vrai UTC (`icsDate.date`) au lieu du fake UTC (`icsDate.local.date`), corrigeant l'affichage scheduler
- Ajouter un helper `getDateComponentsInTimezone(date, timezone)` utilisant `Intl.DateTimeFormat` pour extraire les composants date/heure dans n'importe quel timezone cible
- Refactorer `jsDateToIcsDate()` pour supprimer le paramètre `isFakeUtc` et utiliser le nouveau helper — le fake UTC n'est plus créé par copie aveugle mais par conversion explicite via Intl API
- Nettoyer `toIcsEvent()` pour supprimer la variable `isFakeUtc` et la logique conditionnelle associée
- Conserver le pattern fake UTC **uniquement** au point d'entrée vers ts-ics (`jsDateToIcsDate` et `EventModal.handleSave`), car ts-ics utilise `getUTCHours()` pour générer l'ICS — c'est une contrainte de la librairie, pas un choix d'architecture

## Capabilities

### New Capabilities

- `timezone-conversion`: Gestion correcte des conversions de dates entre timezones dans l'adapter CalDAV ↔ EventCalendar, incluant le support cross-timezone et DST via Intl API

### Modified Capabilities

_(aucune capability existante modifiée au niveau des specs)_

## Impact

- **Code frontend** : `EventCalendarAdapter.ts` (3 méthodes modifiées, 1 ajoutée), `toIcsEvent` simplifié
- **Pas de changement** : `EventModal.tsx`, `dateFormatters.ts`, `useSchedulerHandlers.ts`, backend Django, CalDAV server
- **Pas de changement d'API** : le format ICS envoyé au CalDAV server reste identique (DTSTART avec TZID)
- **Dépendances** : aucune nouvelle dépendance (utilise `Intl.DateTimeFormat` natif du navigateur)
- **Risque** : faible — le changement est isolé dans l'adapter, les tests existants couvrent le round-trip
