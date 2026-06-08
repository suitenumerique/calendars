<?php
/**
 * CalendarSanitizerPlugin - Sanitizes calendar data on all CalDAV writes.
 *
 * Applied to both new creates (PUT to new URI) and updates (PUT to existing URI).
 * This covers events coming from any CalDAV client (Thunderbird, Apple Calendar,
 * Outlook, etc.) as well as the bulk import plugin.
 *
 * Sanitizations:
 * 1. Strip inline binary attachments (ATTACH;VALUE=BINARY / ENCODING=BASE64)
 *    and ATTACH entries whose URI scheme isn't on the allowlist
 *    (http/https/mailto/cid). Blocks file:// exfiltration, smb:// NTLM
 *    hash leaks, javascript: XSS-in-client. URL-based HTTPS attachments
 *    (e.g. Google Drive links) are preserved.
 * 2. Truncate oversized text properties:
 *    - Long text fields (DESCRIPTION, X-ALT-DESC, COMMENT): configurable limit (default 100KB)
 *    - Short text fields (SUMMARY, LOCATION): fixed 1KB safety guardrail
 * 3. Bound unbounded RRULEs (no COUNT/UNTIL) with a per-FREQ COUNT cap.
 *    Strips MINUTELY/SECONDLY RRULEs that can't be safely iterated.
 * 4. Enforce max resource size (default 1MB) on the final serialized object.
 *    Returns HTTP 507 Insufficient Storage if exceeded after sanitization.
 *
 * Controlled by constructor parameters (read from env vars in server.php).
 */

namespace Calendars\SabreDav;

use Sabre\DAV\Server;
use Sabre\DAV\ServerPlugin;
use Sabre\DAV\Exception\InsufficientStorage;
use Sabre\VObject\Reader;
use Sabre\VObject\Component\VCalendar;

class CalendarSanitizerPlugin extends ServerPlugin
{
    /** @var Server */
    protected $server;

    /** @var bool Whether to strip inline binary attachments */
    private $stripBinaryAttachments;

    /** @var int Max size in bytes for long text properties: DESCRIPTION, X-ALT-DESC, COMMENT (0 = no limit) */
    private $maxDescriptionBytes;

    /** @var int Max total resource size in bytes after sanitization (0 = no limit) */
    private $maxResourceSize;

    /** @var int Max size in bytes for short text properties: SUMMARY, LOCATION */
    private const MAX_SHORT_TEXT_BYTES = 1024;

    /** @var array Long text properties subject to $maxDescriptionBytes */
    private const LONG_TEXT_PROPERTIES = ['DESCRIPTION', 'X-ALT-DESC', 'COMMENT'];

    /** @var array Short text properties subject to MAX_SHORT_TEXT_BYTES */
    private const SHORT_TEXT_PROPERTIES = ['SUMMARY', 'LOCATION'];

    /**
     * URI schemes allowed in `ATTACH` properties.
     *
     * Other schemes get the property stripped on write. Rationale:
     *   - `file://`        — auto-fetched by some clients → local
     *     file exfiltration via SCHEDULE-FORCE-SEND-style chains.
     *   - `smb://` / `cifs://` / `ftp://...\\...` — credential
     *     prompt / NTLM hash leak when a Windows client auto-fetches.
     *   - `javascript:` / `vbscript:` / `data:text/html;…` — XSS in
     *     clients that render the attachment URI as a link target.
     *   - Bare schemes / unknown — drop by default; the allowlist is
     *     opt-in.
     *
     * `cid:` is allowed because some clients reference inline images
     * already embedded in the iTIP MIME envelope.
     */
    private const ATTACH_URI_ALLOWED_SCHEMES = ['http', 'https', 'mailto', 'cid'];

    public function __construct(
        bool $stripBinaryAttachments = true,
        int $maxDescriptionBytes = 102400,
        int $maxResourceSize = 1048576,
        ?array $rruleCaps = null
    ) {
        $this->stripBinaryAttachments = $stripBinaryAttachments;
        $this->maxDescriptionBytes = $maxDescriptionBytes;
        $this->maxResourceSize = $maxResourceSize;
        $this->rruleCaps = $rruleCaps ?? self::DEFAULT_RRULE_CAPS;
    }

    public function getPluginName()
    {
        return 'calendar-sanitizer';
    }

    public function initialize(Server $server)
    {
        $this->server = $server;

        // Priority 85: run before AttendeeNormalizerPlugin (90) and CalDAV validation (100)
        $server->on('beforeCreateFile', [$this, 'beforeCreateCalendarObject'], 85);
        $server->on('beforeWriteContent', [$this, 'beforeUpdateCalendarObject'], 85);
    }

    /**
     * Called before a calendar object is created.
     * Signature: ($path, &$data, \Sabre\DAV\ICollection $parent, &$modified)
     */
    public function beforeCreateCalendarObject($path, &$data, $parentNode = null, &$modified = false)
    {
        // Only sanitize files going into a calendar collection.
        // beforeCreateFile fires for ANY file in any collection, including
        // scheduling inboxes and notifications — we don't want to mangle
        // those. Gating on the parent node type is the same check
        // SabreDAV's CalDAV\Plugin uses to decide whether to validate.
        if (!$parentNode instanceof \Sabre\CalDAV\ICalendar) {
            return;
        }
        $this->sanitizeCalendarData($path, $data, $modified);
    }

    /**
     * Called before a calendar object is updated.
     * Signature: ($path, \Sabre\DAV\IFile $node, &$data, &$modified)
     */
    public function beforeUpdateCalendarObject($path, $node, &$data, &$modified = false)
    {
        if (!$node instanceof \Sabre\CalDAV\ICalendarObject) {
            return;
        }
        $this->sanitizeCalendarData($path, $data, $modified);
    }

    /**
     * Default per-frequency COUNT caps for unbounded RRULEs.
     *
     * COUNT bounds the number of *occurrences* directly. UNTIL would
     * leave us open to BY-expansion attacks: an iTIP REQUEST with
     * `FREQ=DAILY;BYHOUR=0,1,...,23` (no UNTIL/COUNT) under a
     * 20-year UNTIL injection expands to ~175k instances, blowing
     * past `maxRecurrences` and 500-ing every subsequent read of
     * the stored event. With COUNT, vobject stops at the bound
     * regardless of BY-fan-out.
     *
     * Values are chosen so that INTERVAL=1 + no BY-expansion roughly
     * matches the human intent in the comments (e.g. ~20 years of
     * DAILY). BY-expansion compresses the time span proportionally,
     * which is fine — the event is still bounded.
     *
     * Every value MUST stay strictly under
     * `Sabre\VObject\Settings::$maxRecurrences` (8000, set in
     * server.php) so vobject's iterator never trips.
     *
     * MINUTELY and SECONDLY are intentionally absent — they are
     * stripped from the event entirely (see STRIPPED_FREQUENCIES).
     */
    public const DEFAULT_RRULE_CAPS = [
        'DAILY'   => 7300,  // ~20 years of daily occurrences
        'WEEKLY'  => 2600,  // ~50 years of weekly occurrences
        'MONTHLY' => 600,   // ~50 years of monthly occurrences
        'YEARLY'  => 100,   // 100 yearly occurrences
        'HOURLY'  => 720,   // ~30 days of hourly occurrences
    ];

    /**
     * Frequencies where the RRULE is stripped on inbound writes (PUT,
     * iTIP routing, imports), leaving the master VEVENT as a one-off.
     *
     * `sabre/vobject`'s `RRuleIterator::next()` has no case for
     * MINUTELY/SECONDLY: the clock never advances, so neither UNTIL nor
     * COUNT can effectively bound iteration. We can't safely store these
     * RRULEs at all.
     *
     * Stripping (rather than rejecting) keeps bulk .ics imports and
     * iTIP REQUEST routing from failing wholesale when a single event
     * in a batch carries one of these frequencies — the master VEVENT
     * still lands in the calendar as a non-recurring occurrence.
     */
    public const STRIPPED_FREQUENCIES = ['MINUTELY', 'SECONDLY'];

    /** @var array<string, int> */
    private array $rruleCaps;

    /**
     * Approximate seconds per FREQ step. MONTHLY uses the shortest
     * month (28 d) so the instance estimate is upper-bound — we'd
     * rather over-clamp than under-clamp.
     */
    private const FREQ_SECONDS = [
        'YEARLY'  => 86400 * 365,
        'MONTHLY' => 86400 * 28,
        'WEEKLY'  => 86400 * 7,
        'DAILY'   => 86400,
        'HOURLY'  => 3600,
    ];

    /**
     * Per-FREQ list of BY-parts that EXPAND (multiply occurrences)
     * per RFC 5545 §3.3.10 Table 1. Anything not listed is a filter
     * (or N/A) and doesn't multiply.
     *
     * BYSETPOS is never an expander — always a post-filter on the
     * generated set, so it's omitted here.
     */
    private const BY_EXPANSION_PARTS = [
        'YEARLY'  => ['BYMONTH', 'BYWEEKNO', 'BYYEARDAY', 'BYMONTHDAY', 'BYDAY', 'BYHOUR', 'BYMINUTE', 'BYSECOND'],
        'MONTHLY' => ['BYMONTHDAY', 'BYDAY', 'BYHOUR', 'BYMINUTE', 'BYSECOND'],
        'WEEKLY'  => ['BYDAY', 'BYHOUR', 'BYMINUTE', 'BYSECOND'],
        'DAILY'   => ['BYHOUR', 'BYMINUTE', 'BYSECOND'],
        'HOURLY'  => ['BYMINUTE', 'BYSECOND'],
    ];

    /**
     * Heuristic cutoff for clamping unparseable UNTIL on a VTODO
     * without DTSTART — `estimateInstances` returns null in that
     * case because we can't compute a delta, and an attacker could
     * smuggle ``RRULE:FREQ=DAILY;UNTIL=99991231T000000Z`` past the
     * cap by omitting DTSTART (legal on VTODO). If the parsed UNTIL
     * year is past this, force a COUNT clamp anyway.
     */
    private const ABSURD_UNTIL_YEAR = 2300;

    /**
     * Return a sanitized RRULE parts array if the rule needs bounding,
     * or null if the existing rule is already safe.
     */
    private function boundRrule(array $parts, string $freq, int $cap, $component): ?array
    {
        $hasCount = isset($parts['COUNT']);
        $hasUntil = isset($parts['UNTIL']);

        if (!$hasCount && !$hasUntil) {
            $parts['COUNT'] = (string) $cap;
            return $parts;
        }

        $estimated = $this->estimateInstances($parts, $freq, $component);

        if ($estimated === null) {
            // Can't estimate (e.g. VTODO with UNTIL but no DTSTART).
            // Defuse the obvious attack: clamp if UNTIL is absurd.
            if ($hasUntil) {
                $until = $this->parseRRuleUntil((string) $parts['UNTIL']);
                if ($until !== null
                    && (int) $until->format('Y') > self::ABSURD_UNTIL_YEAR
                ) {
                    unset($parts['UNTIL']);
                    $parts['COUNT'] = (string) $cap;
                    return $parts;
                }
            }
            return null;
        }
        if ($estimated <= $cap) {
            return null;
        }

        unset($parts['COUNT'], $parts['UNTIL']);
        $parts['COUNT'] = (string) $cap;
        return $parts;
    }

    /**
     * Upper-bound estimate of how many occurrences the RRULE would
     * produce, factoring INTERVAL and BY-expansion. Returns null when
     * we can't estimate (unknown FREQ, missing DTSTART for UNTIL, …).
     */
    private function estimateInstances(array $parts, string $freq, $component): ?int
    {
        $interval = isset($parts['INTERVAL']) ? max(1, (int) $parts['INTERVAL']) : 1;

        $base = null;
        if (isset($parts['COUNT'])) {
            $base = (int) $parts['COUNT'];
        } elseif (isset($parts['UNTIL'])) {
            if (!isset($component->DTSTART)) {
                return null;
            }
            $until = $this->parseRRuleUntil((string) $parts['UNTIL']);
            if ($until === null) {
                return null;
            }
            try {
                $dtstart = $component->DTSTART->getDateTime();
            } catch (\Exception $e) {
                return null;
            }
            $deltaSecs = max(0, $until->getTimestamp() - $dtstart->getTimestamp());
            $perFreqSecs = self::FREQ_SECONDS[$freq] ?? null;
            if ($perFreqSecs === null) {
                return null;
            }
            $base = (int) ceil($deltaSecs / $perFreqSecs / $interval) + 1;
        }
        if ($base === null) {
            return null;
        }
        // ``$base * factor`` can overflow PHP_INT_MAX for absurd
        // COUNT × BY-expansion inputs (COUNT=999999 + BYHOUR=0..23 +
        // BYMINUTE=0..59 etc). PHP promotes overflow to float, which
        // PRESERVES the ``$estimated > $cap`` comparison (float >= int
        // works numerically), so the clamp still fires. Do not
        // introduce a pre-multiplication bounds check here — it would
        // short-circuit the clamp on the very inputs we want to clamp.
        return $base * $this->byExpansionFactor($parts, $freq);
    }

    /**
     * Multiplicative upper bound of BY-expansion for the given FREQ.
     * Per RFC 5545 §3.3.10 Table 1, some BY-parts EXPAND and others
     * FILTER depending on FREQ — see ``BY_EXPANSION_PARTS``. Only
     * counts expanders so a benign filter (``BYMONTH=6`` on
     * ``FREQ=MONTHLY``) doesn't trip a false clamp.
     */
    private function byExpansionFactor(array $parts, string $freq): int
    {
        $expanders = self::BY_EXPANSION_PARTS[$freq] ?? [];
        $factor = 1;
        foreach ($expanders as $key) {
            if (!isset($parts[$key])) {
                continue;
            }
            $values = is_array($parts[$key]) ? $parts[$key] : [$parts[$key]];
            $factor *= max(1, count($values));
        }
        return $factor;
    }

    /**
     * VTIMEZONE STANDARD/DAYLIGHT FREQs we refuse to store.
     *
     * Real-world timezone transitions are at most annual
     * (`FREQ=YEARLY;BYMONTH=…;BYDAY=…`). Anything sub-monthly is
     * either a malformed rule or a deliberate iteration bomb: a
     * `FREQ=DAILY` STANDARD rule means vobject's TimeZoneUtil
     * produces 365 transitions per year while resolving the TZID
     * for any event that uses it, hitting `maxRecurrences` and
     * 500-ing every read. Strip the RRULE in those cases — the
     * STANDARD/DAYLIGHT subcomponent then describes a single
     * transition at its DTSTART, which vobject can handle.
     */
    private const VTIMEZONE_DISALLOWED_FREQS = [
        'SECONDLY', 'MINUTELY', 'HOURLY', 'DAILY', 'WEEKLY',
    ];

    /**
     * Strip malicious RRULEs from a VTIMEZONE's STANDARD/DAYLIGHT
     * subcomponents.
     *
     * @return bool True if anything was modified.
     */
    private function sanitizeVTimezone($vtimezone): bool
    {
        $modified = false;
        foreach ($vtimezone->getComponents() as $sub) {
            if ($sub->name !== 'STANDARD' && $sub->name !== 'DAYLIGHT') {
                continue;
            }
            if (!isset($sub->RRULE)) {
                continue;
            }
            foreach ($sub->select('RRULE') as $rrule) {
                $parts = $rrule->getParts();
                $freq = isset($parts['FREQ'])
                    ? strtoupper((string) $parts['FREQ'])
                    : null;
                if ($freq === null) {
                    continue;
                }
                if (in_array($freq, self::VTIMEZONE_DISALLOWED_FREQS, true)) {
                    $sub->remove($rrule);
                    $modified = true;
                }
            }
        }
        return $modified;
    }

    /**
     * Parse an UNTIL value (DATE or DATE-TIME, UTC or floating) into
     * a `DateTimeImmutable`. Returns null on malformed input — the
     * caller treats this as "can't estimate", which is safe.
     */
    private function parseRRuleUntil(string $raw): ?\DateTimeImmutable
    {
        $raw = strtoupper(trim($raw));
        if (preg_match('/^\d{8}$/', $raw)) {
            $dt = \DateTimeImmutable::createFromFormat(
                '!Ymd', $raw, new \DateTimeZone('UTC')
            );
        } elseif (preg_match('/^\d{8}T\d{6}Z$/', $raw)) {
            $dt = \DateTimeImmutable::createFromFormat(
                '!Ymd\THis\Z', $raw, new \DateTimeZone('UTC')
            );
        } elseif (preg_match('/^\d{8}T\d{6}$/', $raw)) {
            $dt = \DateTimeImmutable::createFromFormat('!Ymd\THis', $raw);
        } else {
            return null;
        }
        return $dt instanceof \DateTimeImmutable ? $dt : null;
    }

    private function sanitizeCalendarData($path, &$data, &$modified)
    {
        // Get the data as string. (`stream_get_contents` / `rewind`
        // don't throw on a closed stream — they return false / fail
        // silently — so no try/catch needed here.)
        if (is_resource($data)) {
            $dataStr = stream_get_contents($data);
            rewind($data);
        } else {
            $dataStr = $data;
        }

        // Reader::read throws on malformed iCal. We catch ONLY there
        // and let downstream validators surface a clean 4xx — that's
        // the only "expected" exception in this flow. Errors thrown
        // during sanitizeVCalendar / serialize would be internal bugs
        // and must propagate so we fail-closed instead of silently
        // letting unsanitized bytes hit storage.
        try {
            $vcalendar = Reader::read($dataStr);
        } catch (\Exception $e) {
            error_log(
                "[CalendarSanitizerPlugin] iCalendar parse error: "
                . $e->getMessage()
            );
            return;
        }

        if (!$vcalendar instanceof VCalendar) {
            return;
        }

        try {
            // Run the structural sanitizer first (binary attachments,
            // long text truncation, RRULE caps, …). The return value
            // tells us whether anything was structurally changed, but we
            // do NOT use it to decide whether to re-serialize.
            $this->sanitizeVCalendar($vcalendar);

            // SECURITY INVARIANT: every byte that lands in calendarobjects
            // (and therefore in every downstream consumer — SabreDAV reads,
            // SharedCalendarPrivacyPlugin parses, the iMIP callback chain,
            // the Django regex/icalendar parser, the frontend ts-ics
            // parser) MUST first round-trip through vobject's serializer.
            //
            // Why: vobject normalizes line folding, escapes control
            // characters in TEXT properties (CR/LF → \n, comma/semicolon
            // → \,/\;), strips control chars from parameter values, and
            // canonicalizes property ordering. Without that round-trip,
            // raw client bytes (which can contain literal CR/LF inside
            // a value, malformed line folds, or property collisions)
            // can flow through to downstream parsers and create field-
            // smuggling primitives. We pin the invariant by re-serializing
            // unconditionally — even when ``sanitizeVCalendar`` didn't
            // structurally modify anything — so the stored form is
            // ALWAYS the canonical vobject output, not the raw bytes.
            //
            // The cost is one extra serialize() per CalDAV write
            // (microseconds for typical events). The benefit is that
            // every downstream "is the byte stream safe" check has a
            // single, simple, easy-to-test answer: yes, because every
            // write passes through this plugin and this plugin always
            // canonicalizes. The N1 line-injection regression suite in
            // the backend tests pins the contract; this plugin makes
            // the contract structurally true.
            $serialized = $vcalendar->serialize();
            if ($serialized !== $dataStr) {
                $data = $serialized;
                $modified = true;
            }

            // Enforce max resource size after canonicalization
            $finalSize = is_string($data) ? strlen($data) : strlen($dataStr);
            if ($this->maxResourceSize > 0 && $finalSize > $this->maxResourceSize) {
                throw new InsufficientStorage(
                    "Calendar object size ({$finalSize} bytes) exceeds limit ({$this->maxResourceSize} bytes)"
                );
            }
        } catch (InsufficientStorage $e) {
            // Re-throw size limit errors — these must reach the client as HTTP 507
            throw $e;
        }
    }

    /**
     * Sanitize a parsed VCalendar object in-place.
     * Strips binary attachments and truncates oversized descriptions.
     *
     * Also called by InternalApiPlugin for direct DB writes that bypass
     * the HTTP layer (and thus don't trigger beforeCreateFile hooks).
     *
     * @return bool True if the VCalendar was modified.
     */
    public function sanitizeVCalendar(VCalendar $vcalendar)
    {
        $wasModified = false;

        foreach ($vcalendar->getComponents() as $component) {
            if ($component->name === 'VTIMEZONE') {
                if ($this->sanitizeVTimezone($component)) {
                    $wasModified = true;
                }
                continue;
            }

            // Strip inline binary attachments and dangerous URI
            // schemes (file://, smb://, javascript:, …).
            //
            // The URI-scheme allowlist runs unconditionally — turning
            // off ``stripBinaryAttachments`` should only re-enable
            // base64/binary payloads, not re-enable ``file://`` /
            // ``smb://`` / ``javascript:`` URIs whose risk is
            // independent of the inline-binary path.
            if (isset($component->ATTACH)) {
                $toRemove = [];
                foreach ($component->select('ATTACH') as $attach) {
                    $valueParam = $attach->offsetGet('VALUE');
                    $encodingParam = $attach->offsetGet('ENCODING');
                    $isBinary = (
                        ($valueParam && strtoupper((string)$valueParam) === 'BINARY') ||
                        ($encodingParam && strtoupper((string)$encodingParam) === 'BASE64')
                    );
                    if ($isBinary) {
                        if ($this->stripBinaryAttachments) {
                            $toRemove[] = $attach;
                        }
                        continue;
                    }
                    $uri = (string) $attach;
                    if ($uri === '') {
                        continue;
                    }
                    $scheme = strtolower((string) parse_url($uri, PHP_URL_SCHEME));
                    if (
                        $scheme === ''
                        || !in_array($scheme, self::ATTACH_URI_ALLOWED_SCHEMES, true)
                    ) {
                        $toRemove[] = $attach;
                    }
                }
                foreach ($toRemove as $attach) {
                    $component->remove($attach);
                    $wasModified = true;
                }
            }

            // Strip RDATE;VALUE=PERIOD. vobject's recurrence expander
            // (RRuleIterator / RDateIterator) throws InvalidDataException
            // when it hits a PERIOD-valued RDATE, which 500s EVERY
            // calendar-query `expand` REPORT over the affected range —
            // and the frontend renders its grid via those REPORTs, so a
            // single such event blanks the entire calendar view (and the
            // user can't see the event in-app to delete it). PERIOD
            // RDATEs are rare and RFC-valid but unsupported by our
            // expand path; drop just those properties so the DTSTART
            // occurrence (and any DATE/DATE-TIME RDATEs) survive.
            if (isset($component->RDATE)) {
                $toRemove = [];
                foreach ($component->select('RDATE') as $rdate) {
                    $valueParam = $rdate->offsetGet('VALUE');
                    if ($valueParam && strtoupper((string) $valueParam) === 'PERIOD') {
                        $toRemove[] = $rdate;
                    }
                }
                foreach ($toRemove as $rdate) {
                    $component->remove($rdate);
                    $wasModified = true;
                }
            }

            // Truncate oversized long text properties (DESCRIPTION,
            // X-ALT-DESC, COMMENT). Uses ``mb_strcut`` so a
            // truncation that lands inside a multi-byte UTF-8
            // sequence backs up to the previous valid boundary
            // instead of emitting an invalid byte stream.
            if ($this->maxDescriptionBytes > 0) {
                foreach (self::LONG_TEXT_PROPERTIES as $prop) {
                    if (isset($component->{$prop})) {
                        $val = (string)$component->{$prop};
                        if (strlen($val) > $this->maxDescriptionBytes) {
                            $component->{$prop} = mb_strcut(
                                $val, 0, $this->maxDescriptionBytes, 'UTF-8'
                            ) . '...';
                            $wasModified = true;
                        }
                    }
                }
            }

            // Bound every RRULE so vobject's iterator can't trip
            // `Settings::$maxRecurrences`. Three paths:
            //
            //   1. FREQ in STRIPPED_FREQUENCIES → strip RRULE + sibling
            //      EXDATE/RDATE (event survives as one-off).
            //   2. RRULE already has COUNT/UNTIL → estimate the upper-
            //      bound instance count. If > cap, replace the bound
            //      with COUNT=cap. Catches the attacker case
            //      (COUNT=999999, UNTIL=99991231, UNTIL+BY-expansion).
            //   3. RRULE has no COUNT/UNTIL → inject COUNT=cap.
            //
            // We can't keep UNTIL alongside an injected COUNT (RFC 5545
            // §3.3.10 says they're mutually exclusive), so over-bound
            // UNTILs are replaced. Estimates over-count for BY-FILTER
            // parts (BYMONTH on YEARLY filters rather than expands),
            // which means some legitimate events get COUNT-bounded
            // when they didn't need to be — the trade-off keeps the
            // logic simple and errs safely.
            if (isset($component->RRULE)) {
                foreach ($component->select('RRULE') as $rrule) {
                    $parts = $rrule->getParts();
                    $freq = isset($parts['FREQ']) ? strtoupper((string) $parts['FREQ']) : null;
                    if ($freq === null) {
                        continue;
                    }

                    if (in_array($freq, self::STRIPPED_FREQUENCIES, true)) {
                        $component->remove($rrule);
                        $wasModified = true;
                        continue;
                    }

                    // RFC 5545 §3.3.10: COUNT and UNTIL MUST NOT both
                    // appear in one RRULE. Some clients emit both;
                    // vobject stores them verbatim and strict downstream
                    // clients (and re-importers) then reject the event.
                    // Keep COUNT — it's the deterministic occurrence
                    // bound — and drop the redundant UNTIL.
                    if (isset($parts['COUNT']) && isset($parts['UNTIL'])) {
                        unset($parts['UNTIL']);
                        $rrule->setParts($parts);
                        $parts = $rrule->getParts();
                        $wasModified = true;
                    }

                    $cap = $this->rruleCaps[$freq] ?? null;
                    if ($cap === null) {
                        continue;
                    }

                    $bounded = $this->boundRrule($parts, $freq, $cap, $component);
                    if ($bounded !== null) {
                        $rrule->setParts($bounded);
                        $wasModified = true;
                    }
                }

                // Only collapse EXDATE/RDATE if every RRULE was stripped.
                // Removing them while another safe RRULE survives would
                // drop exceptions that still belong to that surviving
                // rule.
                if (!isset($component->RRULE) && !isset($component->RDATE)) {
                    if (isset($component->EXDATE)) {
                        foreach ($component->select('EXDATE') as $p) {
                            $component->remove($p);
                        }
                        $wasModified = true;
                    }
                }
            }

            // Truncate oversized short text properties (SUMMARY,
            // LOCATION). Multi-byte safe (see long-text branch above).
            foreach (self::SHORT_TEXT_PROPERTIES as $prop) {
                if (isset($component->{$prop})) {
                    $val = (string)$component->{$prop};
                    if (strlen($val) > self::MAX_SHORT_TEXT_BYTES) {
                        $component->{$prop} = mb_strcut(
                            $val, 0, self::MAX_SHORT_TEXT_BYTES, 'UTF-8'
                        ) . '...';
                        $wasModified = true;
                    }
                }
            }
        }

        // Final pass: defuse recurrence sets that expand to ZERO
        // instances. Must run after the per-component RRULE/RDATE work
        // above so it sees the already-bounded rules.
        if ($this->defuseEmptyRecurrenceSets($vcalendar)) {
            $wasModified = true;
        }

        return $wasModified;
    }

    /**
     * Strip the recurrence from any VEVENT/VTODO/VJOURNAL whose rule set
     * produces no instances at all (e.g. every occurrence EXDATE'd, or an
     * UNTIL that precedes DTSTART).
     *
     * vobject's ``EventIterator`` throws ``NoInstancesException`` the
     * moment such an event is iterated — which happens during CalDAV
     * validation on PUT (→ HTTP 500, leaking the exception class) and on
     * every subsequent expand REPORT (→ 500, blanking the calendar). We
     * can't store an event nobody can read, so we reduce it to its master
     * occurrence by dropping RRULE/RDATE/EXDATE/EXRULE. The DTSTART event
     * survives as a one-off rather than 500-ing the collection.
     *
     * @return bool True if any component was modified.
     */
    private function defuseEmptyRecurrenceSets(VCalendar $vcalendar): bool
    {
        $modified = false;
        foreach ($vcalendar->getComponents() as $component) {
            if (!in_array($component->name, ['VEVENT', 'VTODO', 'VJOURNAL'], true)) {
                continue;
            }
            // Only recurring masters can yield an empty set. A bare
            // RECURRENCE-ID override (no RRULE/RDATE) is a single instance
            // and is never empty.
            if (!isset($component->RRULE) && !isset($component->RDATE)) {
                continue;
            }
            if (!isset($component->UID)) {
                continue;
            }
            $uid = (string) $component->UID;

            try {
                // Constructing + touching the iterator forces vobject to
                // evaluate the recurrence set; an empty set throws here.
                $it = new \Sabre\VObject\Recur\EventIterator($vcalendar, $uid);
                $it->getDtStart();
            } catch (\Sabre\VObject\Recur\NoInstancesException $e) {
                foreach (['RRULE', 'RDATE', 'EXDATE', 'EXRULE'] as $prop) {
                    while (isset($component->{$prop})) {
                        $component->remove($component->{$prop});
                    }
                }
                $modified = true;
                error_log(
                    "[CalendarSanitizerPlugin] recurrence for UID {$uid} "
                    . "produced no instances; stripped to single occurrence"
                );
            } catch (\Exception $e) {
                // Any other error here is not ours to mask — leave the
                // component untouched so genuine problems still surface
                // downstream rather than being silently mangled.
            }
        }
        return $modified;
    }

    /**
     * Check that a VCalendar's serialized size is within the max resource limit.
     * Called by InternalApiPlugin for the direct DB write path.
     *
     * @throws InsufficientStorage if the serialized size exceeds the limit.
     */
    public function checkResourceSize(VCalendar $vcalendar)
    {
        if ($this->maxResourceSize <= 0) {
            return;
        }

        $size = strlen($vcalendar->serialize());
        if ($size > $this->maxResourceSize) {
            throw new InsufficientStorage(
                "Calendar object size ({$size} bytes) exceeds limit ({$this->maxResourceSize} bytes)"
            );
        }
    }

    public function getPluginInfo()
    {
        return [
            'name' => $this->getPluginName(),
            'description' => 'Sanitizes calendar data (strips binary attachments, truncates descriptions)',
        ];
    }
}
