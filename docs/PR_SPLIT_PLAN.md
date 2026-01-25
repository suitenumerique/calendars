# Plan : Découpage en plusieurs PRs

## Contexte

- **24 commits** depuis `main`
- **158 fichiers** modifiés (+16,943 / -10,848 lignes)
- Travail accumulé sans découpage en PRs

---

## Stratégie

Créer **5-6 branches** depuis `main`, chacune avec des commits logiques,
puis créer une PR pour chaque branche.

**Approche technique :**
1. Rester sur `poc/event-calendar` (branche actuelle de travail)
2. Pour chaque PR : créer une nouvelle branche depuis `main`, copier les
   fichiers pertinents depuis `poc/event-calendar`, commiter

---

## Découpage proposé (6 PRs)

### PR 1 : Backend - Invitations CalDAV avec emails
**Branche** : `feat/caldav-invitations`

**Fichiers :**
- `docker/sabredav/src/AttendeeNormalizerPlugin.php`
- `docker/sabredav/src/HttpCallbackIMipPlugin.php`
- `docker/sabredav/server.php`
- `docker/sabredav/sql/pgsql.calendars.sql`
- `src/backend/core/services/calendar_invitation_service.py`
- `src/backend/core/api/viewsets_caldav.py`
- `src/backend/core/templates/emails/calendar_invitation*.html/txt`
- `src/backend/calendars/settings.py`
- `env.d/development/backend.defaults`
- `env.d/development/caldav.defaults`
- `compose.yaml`

**Description PR** : Ajout du scheduling CalDAV (iTIP) avec envoi d'emails
pour les invitations, mises à jour et annulations.

---

### PR 2 : Frontend - Refactoring CalDavService et helpers
**Branche** : `refactor/caldav-service`

**Fichiers :**
- `features/calendar/services/dav/CalDavService.ts`
- `features/calendar/services/dav/EventCalendarAdapter.ts`
- `features/calendar/services/dav/caldav-helpers.ts`
- `features/calendar/services/dav/helpers/*.ts`
- `features/calendar/services/dav/types/*.ts`
- `features/calendar/services/dav/constants.ts`
- `features/calendar/services/dav/__tests__/*.ts`

**Description PR** : Refactoring du service CalDAV avec extraction des
helpers, meilleure gestion des types et ajout de tests.

---

### PR 3 : Frontend - Composant Scheduler (EventModal, handlers)
**Branche** : `feat/scheduler-component`

**Dépend de** : PR 2

**Fichiers :**
- `features/calendar/components/scheduler/*`
- `features/calendar/components/RecurrenceEditor.tsx`
- `features/calendar/components/RecurrenceEditor.scss`
- `features/calendar/components/AttendeesInput.tsx`
- `features/calendar/components/AttendeesInput.scss`
- `features/calendar/contexts/CalendarContext.tsx`
- `pages/calendar.tsx`
- `pages/calendar.scss`

**Description PR** : Nouveau composant Scheduler avec EventModal pour
la création/édition d'événements, gestion des récurrences et des invités.

---

### PR 4 : Frontend - Refactoring CalendarList modulaire
**Branche** : `refactor/calendar-list`

**Fichiers :**
- `features/calendar/components/calendar-list/*`
- `features/calendar/components/LeftPanel.tsx`
- `features/calendar/components/MiniCalendar.tsx`
- `features/calendar/components/MiniCalendar.scss`
- `features/calendar/components/CreateCalendarModal.tsx`
- `features/calendar/components/CalendarList.scss`
- `features/calendar/components/index.ts`

**Description PR** : Refactoring de CalendarList en composants modulaires
(CalendarItemMenu, CalendarListItem, CalendarModal, DeleteConfirmModal).

---

### PR 5 : Frontend - Support i18n et locales
**Branche** : `feat/calendar-i18n`

**Fichiers :**
- `features/calendar/hooks/useCalendarLocale.ts`
- `features/i18n/*` (si modifié)
- `src/frontend/apps/e2e/__tests__/calendar-locale.test.ts`

**Description PR** : Ajout du support des locales pour le calendrier
avec tests e2e.

---

### PR 6 : Frontend - Nettoyage code mort
**Branche** : `chore/remove-dead-code`

**Fichiers supprimés :**
- `features/ui/components/breadcrumbs/`
- `features/ui/components/circular-progress/`
- `features/ui/components/infinite-scroll/`
- `features/ui/components/info/`
- `features/ui/components/responsive/`
- `features/forms/components/RhfInput.tsx`
- `hooks/useCopyToClipboard.tsx`
- `utils/useLayout.tsx`
- `features/calendar/components/EventModalDeprecated.tsx`
- `features/calendar/components/EventModalAdapter.tsx`
- `features/calendar/hooks/useEventModal.tsx`
- `features/calendar/hooks/useCreateEventModal.tsx`
- `src/frontend/packages/open-calendar/` (package entier)

**Description PR** : Suppression du code mort et des composants inutilisés.

---

## Ordre de merge recommandé

```
1. PR 1 (Backend invitations)     - indépendante
2. PR 2 (CalDavService)           - indépendante
3. PR 6 (Dead code)               - indépendante
4. PR 5 (i18n)                    - indépendante
5. PR 4 (CalendarList)            - après PR 6
6. PR 3 (Scheduler)               - après PR 2, PR 4
```

---

## Étapes d'exécution

Pour chaque PR :

```bash
# 1. Créer la branche depuis main
git checkout main
git pull origin main
git checkout -b <branch-name>

# 2. Copier les fichiers depuis poc/event-calendar
git checkout poc/event-calendar -- <fichiers>

# 3. Vérifier et commiter
git add .
git commit -m "..."

# 4. Pousser et créer la PR
git push -u origin <branch-name>
gh pr create --title "..." --body "..."
```

---

## Fichiers à exclure des PRs

- `CLAUDE.md` (fichier local)
- `IMPLEMENTATION_CHECKLIST.md`, `README_RECURRENCE.md`, etc.
  (documentation temporaire à supprimer ou consolider)

---

## Vérification

Avant chaque PR :
```bash
cd src/frontend/apps/calendars
yarn tsc --noEmit   # Types OK
yarn lint           # Lint OK
yarn test           # Tests OK
```

---

## Faisabilité

**Oui, c'est tout à fait possible.** La stratégie `git checkout <branch> -- <files>`
permet de récupérer des fichiers spécifiques d'une branche sans perdre
l'historique de travail. Chaque PR sera autonome et reviewable indépendamment.
