## Context

L'application utilise un pattern "fake UTC" pour communiquer avec la librairie `ts-ics`. Ce pattern consiste à créer des objets `Date` JavaScript dont les composants UTC (`getUTCHours()`, etc.) représentent l'heure locale voulue, car `ts-ics` utilise `getUTCHours()` pour générer les chaînes ICS.

Le problème : ce pattern fuit dans le chemin d'affichage. La méthode `icsDateToJsDate()` retourne `icsDate.local.date` (un fake UTC) et `dateToLocalISOString()` appelle `getHours()` dessus. Le navigateur ajoute alors son propre offset timezone, ce qui double la conversion.

```
ts-ics parse: DTSTART;TZID=Europe/Paris:20260129T150000

  date       = Date(UTC 14:00)     ← vrai UTC (15h Paris - 1h offset)
  local.date = Date(UTC 15:00)     ← fake UTC (getUTCHours=15)

Actuel (bugué):
  icsDateToJsDate() → local.date → Date(UTC 15:00)
  dateToLocalISOString() → getHours() → 16h (navigateur ajoute +1h)
  Affichage: 16:00 ❌

Corrigé:
  icsDateToJsDate() → date → Date(UTC 14:00)
  dateToLocalISOString() → getHours() → 15h (navigateur convertit correctement)
  Affichage: 15:00 ✅
```

## Goals / Non-Goals

**Goals:**

- Corriger l'affichage des événements dans le scheduler (suppression du décalage timezone)
- Gérer correctement les événements cross-timezone (event créé à New York, vu depuis Paris)
- Gérer correctement les transitions DST (heure d'été/hiver)
- Confiner le pattern fake UTC au strict minimum : le point d'entrée vers `ts-ics`

**Non-Goals:**

- Remplacer `ts-ics` par une autre librairie
- Brancher le champ `timezone` du profil utilisateur (prévu mais hors scope)
- Ajouter un sélecteur de timezone dans l'UI
- Modifier le backend Django ou le CalDAV server SabreDAV
- Modifier l'EventModal ou les dateFormatters (ils fonctionnent correctement)

## Decisions

### Decision 1 : Retourner le vrai UTC dans `icsDateToJsDate()`

**Choix** : Retourner `icsDate.date` (vrai UTC) au lieu de `icsDate.local.date` (fake UTC).

**Rationale** : `dateToLocalISOString()` utilise `getHours()` qui applique automatiquement l'offset du navigateur. Avec un vrai UTC en entrée, la conversion navigateur donne directement l'heure locale correcte. Plus besoin de flag `isFakeUtc` dans le chemin d'affichage.

**Alternative rejetée** : Modifier `dateToLocalISOString()` pour utiliser `getUTCHours()` quand la date est fake UTC. Rejeté car cela propagerait le concept de fake UTC plus loin dans le code au lieu de le contenir.

### Decision 2 : Utiliser `Intl.DateTimeFormat` pour la conversion timezone dans `jsDateToIcsDate()`

**Choix** : Ajouter un helper `getDateComponentsInTimezone(date, timezone)` qui utilise `Intl.DateTimeFormat` avec le paramètre `timeZone` pour extraire les composants (year, month, day, hours, minutes, seconds) dans le timezone cible. Utiliser ces composants pour créer le fake UTC destiné à `ts-ics`.

**Rationale** : C'est la seule approche qui gère correctement :
1. **Même timezone** : event créé et vu en France → `Intl(tz=Europe/Paris)` donne l'heure locale française
2. **Cross-timezone** : event créé à NY, vu en France → `Intl(tz=America/New_York)` donne l'heure new-yorkaise
3. **DST** : transitions automatiquement gérées par le moteur `Intl` du navigateur

**Alternative rejetée** : Calculer l'offset manuellement avec `getTimezoneOffset()`. Rejeté car ne gère pas les transitions DST correctement pour les timezones arbitraires.

### Decision 3 : Conserver le fake UTC au point d'entrée ts-ics

**Choix** : Le fake UTC reste dans `jsDateToIcsDate()` (adapter) et `handleSave()` (EventModal) — les deux seuls endroits qui produisent des `IcsEvent` pour `ts-ics`.

**Rationale** : `ts-ics` utilise `date.getUTCHours()` pour générer les chaînes ICS (`DTSTART;TZID=Europe/Paris:20260129T150000`). C'est une contrainte de la librairie qui ne peut pas être contournée sans la forker. Le fake UTC est le pattern correct pour cette interface — le problème n'était pas le pattern lui-même, mais sa fuite dans le chemin d'affichage.

```
                    Frontière fake UTC
                           │
  Affichage (vrai UTC)     │   ts-ics (fake UTC)
  ─────────────────────────┼───────────────────
  icsDateToJsDate()        │   jsDateToIcsDate()
  dateToLocalISOString()   │   handleSave()
  EventCalendar UI         │   generateIcsCalendar()
                           │
  getHours() → local OK    │   getUTCHours() → local OK
```

### Decision 4 : Supprimer le paramètre `isFakeUtc` de `jsDateToIcsDate()`

**Choix** : Le paramètre `isFakeUtc` est remplacé par la conversion explicite via `Intl.DateTimeFormat`. La méthode reçoit toujours un vrai UTC (ou une Date en heure locale du navigateur — c'est le même objet JS, seule l'interprétation change) et le convertit dans le timezone cible.

**Rationale** : L'ancien code avait deux chemins :
- `isFakeUtc = true` → passe la date telle quelle (suppose que les composants UTC sont déjà corrects)
- `isFakeUtc = false` → copie les composants locaux (`getHours()`) dans un nouveau `Date.UTC()`

Le nouveau code n'a qu'un seul chemin : extraire les composants dans le timezone cible via `Intl`, puis créer le fake UTC. Cela élimine une catégorie entière de bugs (mauvaise valeur de `isFakeUtc`).

## Risks / Trade-offs

**[Régression EventModal]** → Le modal reçoit des IcsEvent avec des dates fake UTC (produites par `jsDateToIcsDate`). Il utilise `isFakeUtc` + `getUTCHours()` pour les lire. Ce chemin n'est pas modifié et reste correct. Vérifié : le `isFakeUtc` dans le modal détecte `event.start.local?.timezone`, qui est toujours présent sur les dates fake UTC produites par l'adapter.

**[Performance Intl.DateTimeFormat]** → `Intl.DateTimeFormat` crée un formateur à chaque appel. Mitigation : impact négligeable car appelé uniquement à la sauvegarde (pas à chaque rendu). Si nécessaire, on peut cacher les formateurs par timezone.

**[Navigateurs anciens]** → `Intl.DateTimeFormat` avec `formatToParts()` est supporté depuis Chrome 56, Firefox 51, Safari 11. Tous les navigateurs cibles de l'app le supportent. Déjà utilisé dans `getTimezoneOffset()`.

**[Events sans TZID (UTC pur)]** → `DTSTART:20260129T150000Z` → ts-ics produit `date = Date(UTC 15:00)` sans propriété `local`. `icsDateToJsDate()` retourne déjà `date` dans ce cas. Aucun changement de comportement.

**[Events all-day]** → `DTSTART;VALUE=DATE:20260129` → ts-ics produit `date = Date.UTC(2026, 0, 29)` sans `local`. `icsDateToJsDate()` retourne déjà `date`. `dateToDateOnlyString()` utilise `getUTCFullYear/Month/Date()`. Aucun changement de comportement.
