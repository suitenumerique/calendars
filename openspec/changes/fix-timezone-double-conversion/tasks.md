## 1. Helper de conversion timezone

- [x] 1.1 Ajouter le type `DateComponents` (interface avec year, month, day, hours, minutes, seconds) dans `EventCalendarAdapter.ts`
- [x] 1.2 Ajouter la méthode `getDateComponentsInTimezone(date: Date, timezone: string)` dans `EventCalendarAdapter.ts` — utilise `Intl.DateTimeFormat` avec `formatToParts()` pour extraire les composants dans le timezone cible

## 2. Fix du chemin de lecture (affichage)

- [x] 2.1 Modifier `icsDateToJsDate()` dans `EventCalendarAdapter.ts` pour retourner `icsDate.date` au lieu de `icsDate.local?.date` — c'est le fix principal de l'affichage scheduler

## 3. Fix du chemin d'écriture (sauvegarde)

- [x] 3.1 Refactorer `jsDateToIcsDate()` dans `EventCalendarAdapter.ts` : supprimer le paramètre `isFakeUtc`, utiliser `getDateComponentsInTimezone()` pour obtenir les composants dans le timezone cible, créer le fake UTC avec `Date.UTC()` à partir de ces composants
- [x] 3.2 Modifier `toIcsEvent()` dans `EventCalendarAdapter.ts` : supprimer la variable `isFakeUtc` (ligne 347) et ne plus passer ce paramètre à `jsDateToIcsDate()`

## 4. Tests unitaires — getDateComponentsInTimezone

Créer `src/frontend/apps/calendars/src/features/calendar/services/dav/__tests__/timezone-conversion.test.ts`

- [x] 4.1 Test Europe/Paris hiver : `Date("2026-01-29T14:00:00Z")` → `{ hours: 15 }` (CET, UTC+1)
- [x] 4.2 Test Europe/Paris été : `Date("2026-07-15T13:00:00Z")` → `{ hours: 15 }` (CEST, UTC+2)
- [x] 4.3 Test America/New_York hiver : `Date("2026-01-29T15:00:00Z")` → `{ hours: 10 }` (EST, UTC-5)
- [x] 4.4 Test America/New_York été : `Date("2026-07-15T14:00:00Z")` → `{ hours: 10 }` (EDT, UTC-4)
- [x] 4.5 Test Asia/Tokyo (pas de DST) : `Date("2026-01-29T06:00:00Z")` → `{ hours: 15 }` (JST, UTC+9)
- [x] 4.6 Test UTC : `Date("2026-01-29T15:30:45Z")` → `{ hours: 15, minutes: 30, seconds: 45 }`
- [x] 4.7 Test changement de jour (UTC tard → lendemain en avance) : `Date("2026-01-29T23:00:00Z")` + Asia/Tokyo → `{ day: 30, hours: 8 }`
- [x] 4.8 Test changement de jour (UTC tôt → veille en retard) : `Date("2026-01-29T03:00:00Z")` + America/New_York → `{ day: 28, hours: 22 }`
- [x] 4.9 Test changement d'année : `Date("2026-01-01T00:30:00Z")` + America/Los_Angeles → `{ year: 2025, month: 12, day: 31 }`
- [x] 4.10 Test offset demi-heure (Inde) : `Date("2026-01-29T10:00:00Z")` + Asia/Kolkata → `{ hours: 15, minutes: 30 }` (UTC+5:30)
- [x] 4.11 Test offset 45min (Népal) : `Date("2026-01-29T10:00:00Z")` + Asia/Kathmandu → `{ hours: 15, minutes: 45 }` (UTC+5:45)
- [x] 4.12 Test transition DST CET→CEST (mars) : vérifier avant et après la transition du dernier dimanche de mars
- [x] 4.13 Test transition DST CEST→CET (octobre) : vérifier avant et après la transition du dernier dimanche d'octobre
- [x] 4.14 Test minutes et secondes non-zéro : `Date("2026-01-29T14:37:42Z")` + Europe/Paris → `{ hours: 15, minutes: 37, seconds: 42 }`

## 5. Tests unitaires — icsDateToJsDate (fix du bug)

- [x] 5.1 Test : retourne `icsDate.date` (vrai UTC) quand `local` est présent — vérifie que c'est bien `date` et PAS `local.date`
- [x] 5.2 Test : retourne `icsDate.date` quand `local` est absent (événements UTC purs)
- [x] 5.3 Test : retourne `icsDate.date` pour les événements all-day (type DATE)

## 6. Tests unitaires — jsDateToIcsDate (conversion timezone)

- [x] 6.1 Test all-day : produit un `IcsDateObject` de type `DATE` sans timezone
- [x] 6.2 Test Europe/Paris hiver : `Date(UTC 14:00)` + tz Paris → fake UTC avec `getUTCHours() === 15`
- [x] 6.3 Test America/New_York hiver : `Date(UTC 15:00)` + tz NY → fake UTC avec `getUTCHours() === 10`
- [x] 6.4 Test Asia/Tokyo : `Date(UTC 06:00)` + tz Tokyo → fake UTC avec `getUTCHours() === 15`
- [x] 6.5 Test Europe/Paris été (DST) : `Date(UTC 13:00)` + tz Paris → fake UTC avec `getUTCHours() === 15` (CEST, UTC+2)
- [x] 6.6 Test préservation minutes/secondes : `Date(UTC 14:37:42)` + tz Paris → fake UTC avec `getUTCMinutes() === 37`, `getUTCSeconds() === 42`
- [x] 6.7 Test changement de jour : `Date(UTC 23:00)` + tz Tokyo → fake UTC avec `getUTCDate()` = jour suivant
- [x] 6.8 Test que `local.timezone` est correctement défini dans l'objet retourné
- [x] 6.9 Test que `local.tzoffset` est correctement calculé (format "+HHMM" / "-HHMM")

## 7. Tests unitaires — getTimezoneOffset

- [x] 7.1 Test offset positif hiver : Europe/Paris → "+0100"
- [x] 7.2 Test offset positif été : Europe/Paris → "+0200"
- [x] 7.3 Test offset négatif hiver : America/New_York → "-0500"
- [x] 7.4 Test offset négatif été : America/New_York → "-0400"
- [x] 7.5 Test offset zéro : UTC → "+0000"
- [x] 7.6 Test offset demi-heure : Asia/Kolkata → "+0530"
- [x] 7.7 Test timezone invalide : retourne "+0000" (fallback gracieux)

## 8. Tests unitaires — Round-trip complet (parse ICS → adapter → display string → adapter → ICS)

- [x] 8.1 Round-trip Europe/Paris hiver : parse `DTSTART;TZID=Europe/Paris:20260129T150000` → icsDateToJsDate → dateToLocalISOString → parse string → jsDateToIcsDate → vérifier `getUTCHours() === 15`
- [x] 8.2 Round-trip Europe/Paris été : idem avec `20260715T150000` (CEST)
- [x] 8.3 Round-trip America/New_York : parse `DTSTART;TZID=America/New_York:20260129T100000` → round-trip → vérifier `getUTCHours() === 10`
- [x] 8.4 Round-trip Asia/Tokyo : parse `DTSTART;TZID=Asia/Tokyo:20260129T150000` → round-trip → vérifier `getUTCHours() === 15`
- [x] 8.5 Round-trip UTC pur : parse `DTSTART:20260129T140000Z` → round-trip (pas de TZID, utilise browser tz)
- [x] 8.6 Round-trip all-day : parse `DTSTART;VALUE=DATE:20260129` → round-trip → vérifier `getUTCDate() === 29`
- [x] 8.7 Round-trip cross-timezone (NY créé, Paris affiché) : vérifier que l'heure NY est préservée après un round-trip depuis un browser Paris

## 9. Mise à jour des tests existants

- [x] 9.1 Mettre à jour le test `icsDateToJsDate` dans `event-calendar-helper.test.ts` (ligne 514-533) : le test "returns local date when present" doit maintenant vérifier que c'est `icsDate.date` (vrai UTC) qui est retourné, pas `local.date`

## 10. Vérification finale

- [x] 10.1 Vérifier que le TypeScript compile sans erreurs (`yarn tsc --noEmit`)
- [x] 10.2 Vérifier que le linter passe (`yarn lint`)
- [x] 10.3 Vérifier que tous les tests passent (`yarn test`)
