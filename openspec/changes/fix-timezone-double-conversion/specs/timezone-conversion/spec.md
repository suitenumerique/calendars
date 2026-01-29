## ADDED Requirements

### Requirement: Affichage correct des événements timezone-aware dans le scheduler

Le système SHALL afficher les événements avec TZID à l'heure locale correcte du navigateur dans le scheduler. La méthode `icsDateToJsDate()` MUST retourner `icsDate.date` (vrai UTC) pour que `dateToLocalISOString()` produise l'heure locale correcte via `getHours()`.

#### Scenario: Événement Europe/Paris vu depuis la France

- **WHEN** un événement `DTSTART;TZID=Europe/Paris:20260129T150000` est affiché dans un navigateur en France (UTC+1 hiver)
- **THEN** le scheduler affiche l'événement à 15:00

#### Scenario: Événement UTC pur vu depuis la France

- **WHEN** un événement `DTSTART:20260129T140000Z` est affiché dans un navigateur en France (UTC+1 hiver)
- **THEN** le scheduler affiche l'événement à 15:00

#### Scenario: Événement all-day

- **WHEN** un événement `DTSTART;VALUE=DATE:20260129` est affiché
- **THEN** le scheduler affiche l'événement le 29 janvier sans décalage de jour

### Requirement: Conversion cross-timezone correcte à l'écriture

Le système SHALL convertir les dates de l'heure locale du navigateur vers le timezone cible de l'événement lors de la sauvegarde. La conversion MUST utiliser `Intl.DateTimeFormat` avec le paramètre `timeZone` pour extraire les composants date/heure dans le timezone cible.

#### Scenario: Sauvegarde d'un événement local (même timezone)

- **WHEN** un utilisateur en France crée un événement à 15:00 avec timezone `Europe/Paris`
- **THEN** le système génère `DTSTART;TZID=Europe/Paris:20260129T150000`

#### Scenario: Sauvegarde d'un événement cross-timezone sans modification

- **WHEN** un événement `DTSTART;TZID=America/New_York:20260129T100000` est ouvert et sauvegardé sans modification depuis un navigateur en France
- **THEN** le système génère `DTSTART;TZID=America/New_York:20260129T100000` (heure NY préservée)

#### Scenario: Drag & drop d'un événement cross-timezone

- **WHEN** un événement `DTSTART;TZID=America/New_York:20260129T100000` affiché à 16:00 heure de Paris est déplacé à 17:00 sur le scheduler
- **THEN** le système génère `DTSTART;TZID=America/New_York:20260129T110000` (déplacement de +1h dans le timezone NY)

### Requirement: Gestion correcte des transitions DST

Le système SHALL gérer correctement les événements qui traversent une transition d'heure d'été/hiver. La conversion MUST utiliser `Intl.DateTimeFormat` qui résout automatiquement l'offset DST pour la date spécifique.

#### Scenario: Événement en été vu depuis l'hiver

- **WHEN** un événement `DTSTART;TZID=Europe/Paris:20260715T150000` (CEST, UTC+2) est affiché dans un navigateur en France en janvier (CET, UTC+1)
- **THEN** le scheduler affiche l'événement à 15:00 (l'heure Paris est préservée indépendamment du DST du navigateur)

#### Scenario: Round-trip d'un événement été

- **WHEN** un événement `DTSTART;TZID=Europe/Paris:20260715T150000` est ouvert et sauvegardé sans modification
- **THEN** le système génère `DTSTART;TZID=Europe/Paris:20260715T150000` (offset CEST correctement calculé par Intl)

### Requirement: Helper getDateComponentsInTimezone

Le système SHALL fournir une méthode `getDateComponentsInTimezone(date: Date, timezone: string)` qui retourne les composants (year, month, day, hours, minutes, seconds) d'un instant UTC dans le timezone cible. Cette méthode MUST utiliser `Intl.DateTimeFormat` avec `formatToParts()`.

#### Scenario: Extraction des composants Europe/Paris en hiver

- **WHEN** `getDateComponentsInTimezone(Date("2026-01-29T14:00:00Z"), "Europe/Paris")` est appelé
- **THEN** le résultat contient `{ year: 2026, month: 1, day: 29, hours: 15, minutes: 0, seconds: 0 }`

#### Scenario: Extraction des composants America/New_York en hiver

- **WHEN** `getDateComponentsInTimezone(Date("2026-01-29T15:00:00Z"), "America/New_York")` est appelé
- **THEN** le résultat contient `{ year: 2026, month: 1, day: 29, hours: 10, minutes: 0, seconds: 0 }`

#### Scenario: Extraction des composants Europe/Paris en été (CEST)

- **WHEN** `getDateComponentsInTimezone(Date("2026-07-15T13:00:00Z"), "Europe/Paris")` est appelé
- **THEN** le résultat contient `{ year: 2026, month: 7, day: 15, hours: 15, minutes: 0, seconds: 0 }` (UTC+2 en été)

#### Scenario: Extraction des composants Asia/Tokyo (pas de DST)

- **WHEN** `getDateComponentsInTimezone(Date("2026-01-29T06:00:00Z"), "Asia/Tokyo")` est appelé
- **THEN** le résultat contient `{ year: 2026, month: 1, day: 29, hours: 15, minutes: 0, seconds: 0 }` (UTC+9, jamais de DST)

#### Scenario: Changement de jour par conversion timezone (UTC tard → jour suivant en avance)

- **WHEN** `getDateComponentsInTimezone(Date("2026-01-29T23:00:00Z"), "Asia/Tokyo")` est appelé
- **THEN** le résultat contient `{ year: 2026, month: 1, day: 30, hours: 8, minutes: 0, seconds: 0 }` (23h UTC + 9h = 8h le lendemain)

#### Scenario: Changement de jour par conversion timezone (UTC tôt → jour précédent en retard)

- **WHEN** `getDateComponentsInTimezone(Date("2026-01-29T03:00:00Z"), "America/New_York")` est appelé
- **THEN** le résultat contient `{ year: 2026, month: 1, day: 28, hours: 22, minutes: 0, seconds: 0 }` (3h UTC - 5h = 22h la veille)

#### Scenario: Changement d'année par conversion timezone

- **WHEN** `getDateComponentsInTimezone(Date("2026-01-01T00:30:00Z"), "America/Los_Angeles")` est appelé
- **THEN** le résultat contient `{ year: 2025, month: 12, day: 31, hours: 16, minutes: 30, seconds: 0 }` (UTC-8 en hiver)

#### Scenario: UTC comme timezone cible

- **WHEN** `getDateComponentsInTimezone(Date("2026-01-29T15:30:45Z"), "UTC")` est appelé
- **THEN** le résultat contient `{ year: 2026, month: 1, day: 29, hours: 15, minutes: 30, seconds: 45 }`

#### Scenario: Minutes et secondes non-zéro

- **WHEN** `getDateComponentsInTimezone(Date("2026-01-29T14:37:42Z"), "Europe/Paris")` est appelé
- **THEN** le résultat contient `{ year: 2026, month: 1, day: 29, hours: 15, minutes: 37, seconds: 42 }`

#### Scenario: Offset demi-heure (Inde)

- **WHEN** `getDateComponentsInTimezone(Date("2026-01-29T10:00:00Z"), "Asia/Kolkata")` est appelé
- **THEN** le résultat contient `{ year: 2026, month: 1, day: 29, hours: 15, minutes: 30, seconds: 0 }` (UTC+5:30)

#### Scenario: Offset 45 minutes (Népal)

- **WHEN** `getDateComponentsInTimezone(Date("2026-01-29T10:00:00Z"), "Asia/Kathmandu")` est appelé
- **THEN** le résultat contient `{ year: 2026, month: 1, day: 29, hours: 15, minutes: 45, seconds: 0 }` (UTC+5:45)

#### Scenario: Proche de la transition DST Europe/Paris (dernier dimanche de mars)

- **WHEN** `getDateComponentsInTimezone(Date("2026-03-29T00:30:00Z"), "Europe/Paris")` est appelé (avant transition, encore CET)
- **THEN** le résultat contient `{ hours: 1, minutes: 30 }` (UTC+1)

#### Scenario: Après la transition DST Europe/Paris

- **WHEN** `getDateComponentsInTimezone(Date("2026-03-29T02:00:00Z"), "Europe/Paris")` est appelé (après transition, CEST)
- **THEN** le résultat contient `{ hours: 4, minutes: 0 }` (UTC+2)

### Requirement: Confinement du fake UTC à l'interface ts-ics

Le pattern fake UTC (objets Date dont les composants UTC représentent l'heure locale) MUST être confiné à deux endroits uniquement : `jsDateToIcsDate()` dans l'adapter et `handleSave()` dans l'EventModal. Aucun autre code NE DOIT créer ou consommer de dates fake UTC pour l'affichage.

#### Scenario: Le chemin d'affichage n'utilise pas de fake UTC

- **WHEN** `icsDateToJsDate()` est appelé avec un `IcsDateObject` ayant une propriété `local`
- **THEN** la méthode retourne `icsDate.date` (vrai UTC), PAS `icsDate.local.date` (fake UTC)

#### Scenario: jsDateToIcsDate produit du fake UTC pour ts-ics

- **WHEN** `jsDateToIcsDate()` reçoit `Date("2026-01-29T14:00:00Z")` avec timezone `"Europe/Paris"`
- **THEN** l'objet retourné contient `date` avec `getUTCHours() === 15` (fake UTC pour ts-ics)

### Requirement: Tests unitaires exhaustifs des utilitaires de conversion timezone

Le changement MUST inclure un fichier de tests dédié (`__tests__/timezone-conversion.test.ts`) couvrant tous les scénarios de conversion. Les tests MUST utiliser des dates UTC explicites pour être déterministes indépendamment de la timezone de la machine de CI.

#### Scenario: Tests de getDateComponentsInTimezone couvrent toutes les catégories

- **WHEN** la suite de tests est exécutée
- **THEN** les tests couvrent : timezones positives (Europe/Paris, Asia/Tokyo), timezones négatives (America/New_York, America/Los_Angeles), timezone UTC, offsets demi-heure (Asia/Kolkata UTC+5:30), offsets 45min (Asia/Kathmandu UTC+5:45), changements de jour par conversion, changement d'année par conversion, transitions DST (CET→CEST mars, CEST→CET octobre), minutes et secondes non-zéro

#### Scenario: Tests de icsDateToJsDate couvrent la correction du bug

- **WHEN** la suite de tests est exécutée
- **THEN** les tests vérifient que `icsDateToJsDate()` retourne `icsDate.date` quand `local` est présent, retourne `icsDate.date` quand `local` est absent, retourne `icsDate.date` pour les DATE type (all-day)

#### Scenario: Tests de jsDateToIcsDate couvrent la conversion timezone correcte

- **WHEN** la suite de tests est exécutée
- **THEN** les tests vérifient : all-day event produit DATE type, timed event produit DATE-TIME avec timezone, fake UTC a les bons composants UTC pour Europe/Paris hiver, fake UTC a les bons composants UTC pour America/New_York hiver, fake UTC a les bons composants UTC pour Asia/Tokyo, fake UTC a les bons composants UTC pour Europe/Paris été (DST), fake UTC préserve minutes et secondes

#### Scenario: Tests de round-trip (parse → adapter → display → adapter → generate)

- **WHEN** la suite de tests est exécutée
- **THEN** les tests vérifient le round-trip complet pour : événement Europe/Paris hiver, événement Europe/Paris été, événement America/New_York, événement Asia/Tokyo, événement UTC pur, événement all-day, événement cross-timezone (NY vu depuis Paris)

#### Scenario: Tests de getTimezoneOffset couvrent les cas limites

- **WHEN** la suite de tests est exécutée
- **THEN** les tests vérifient : offset positif (Europe/Paris → "+0100" hiver, "+0200" été), offset négatif (America/New_York → "-0500" hiver, "-0400" été), offset zéro (UTC → "+0000"), offset demi-heure (Asia/Kolkata → "+0530"), timezone invalide retourne "+0000"

#### Scenario: Les tests sont déterministes en CI

- **WHEN** les tests sont exécutés sur une machine de CI (timezone potentiellement différente)
- **THEN** tous les tests passent car ils utilisent uniquement des dates UTC explicites (`new Date("...Z")`) et des assertions sur `getUTCHours()` / `getUTCMinutes()` pour les fake UTC, jamais `getHours()` qui dépend de la timezone locale
