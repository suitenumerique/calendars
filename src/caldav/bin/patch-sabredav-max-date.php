<?php
/**
 * Bump SabreDAV's `Sabre\CalDAV\Backend\PDO::MAX_DATE` from
 * `'2038-01-01'` to `'2200-01-01'`.
 *
 * Why: upstream picked 2038 because a 32-bit Unix timestamp tops out
 * at 2147483647 seconds = 2038-01-19. Our `calendarobjects` table
 * uses `BIGINT` columns (see `sql/pgsql.calendars.sql`) and PHP is
 * 64-bit, so the clip is dead weight — it just makes recurrences
 * past 2038 silently drop out of CalDAV time-range REPORTs, because
 * SabreDAV adds `lastoccurence > :startdate` as a SQL pre-filter
 * (see `PDO.php::calendarQuery`) and any rule extending past 2038
 * gets `lastoccurence` clamped to 2038-01-01 at write time.
 *
 * Our sanitizer's per-FREQ COUNT caps push recurrences out to
 * roughly:
 *   - DAILY     ~2046  (COUNT=7300)
 *   - WEEKLY    ~2076  (COUNT=2600)
 *   - MONTHLY   ~2076  (COUNT=600)
 *   - YEARLY    ~2126  (COUNT=100)
 *
 * 2200 covers all of them with headroom. Bumping the constant value
 * directly is portable: this script runs from composer post-install
 * / post-update hooks on every install path (Docker, Scalingo
 * buildpack, local dev), without needing build-system support for
 * vendor patching.
 */

$target = __DIR__ . '/../vendor/sabre/dav/lib/CalDAV/Backend/PDO.php';
if (!file_exists($target)) {
    fwrite(STDERR, "patch-sabredav-max-date: file not found: $target\n");
    exit(1);
}

$needle  = "const MAX_DATE = '2038-01-01';";
$replace = "const MAX_DATE = '2200-01-01';";
$source  = file_get_contents($target);
if ($source === false) {
    fwrite(STDERR, "patch-sabredav-max-date: failed to read $target\n");
    exit(1);
}

$count = substr_count($source, $needle);
if ($count === 0 && substr_count($source, $replace) === 1) {
    echo "patch-sabredav-max-date: already patched\n";
    exit(0);
}
if ($count !== 1) {
    fwrite(
        STDERR,
        "patch-sabredav-max-date: expected exactly one match for needle "
        . "in $target, found $count. SabreDAV release may have changed; "
        . "review and update this script.\n"
    );
    exit(1);
}

$written = file_put_contents($target, str_replace($needle, $replace, $source));
if ($written === false) {
    fwrite(STDERR, "patch-sabredav-max-date: failed to write $target\n");
    exit(1);
}
echo "patch-sabredav-max-date: patched $target\n";
