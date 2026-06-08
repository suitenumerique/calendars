// Test DST scenario
const TODAY = "2026-03-20";

// This is the test date - January (winter time)
const winterDate = new Date("2026-01-29T15:00:00.000");
console.log("Winter date (Jan 29) at 15:00 local:");
console.log("  getHours():", winterDate.getHours());
console.log("  Expected timezone: Europe/Paris CET (UTC+1)");
console.log("  UTC time would be: 14:00");

// But TODAY is March 20, which is after DST started
// So if today is March 20, the browser's local timezone is now CEST (UTC+2)
// The string "2026-01-29T15:00:00.000" will be interpreted as:
// 15:00 in browser's local time (which is currently CEST in this system)
// When the system parses this, it applies the CURRENT browser timezone

const testDate = new Date("2026-01-29T15:00:00.000");
console.log("\nCurrent system timezone info:");
const formatter = new Intl.DateTimeFormat("en-US", {
  timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
console.log("  Current timezone:", Intl.DateTimeFormat().resolvedOptions().timeZone);
console.log("  When parsing 2026-01-29T15:00:00.000:");
console.log("  Browser interprets it as 15:00 local time on Jan 29");
console.log("  But today (March 20), the local timezone rules have changed");
console.log("  In Jan: Europe/Paris is UTC+1 (CET)");
console.log("  In March: Europe/Paris is UTC+2 (CEST)");

// The test expects UTC hours = 15 for Paris local time representation
// But since the parsing date is in January, we need to use the Jan offset

// Check offset on the event date vs today
const parisFormatter = new Intl.DateTimeFormat("en-US", {
  timeZone: "Europe/Paris",
  timeZoneName: "longOffset",
});
const parts = parisFormatter.formatToParts(testDate);
const offsetPart = parts.find((p) => p.type === "timeZoneName");
console.log("\nParisFormatter for 2026-01-29:");
console.log("  Offset:", offsetPart?.value);

// The issue: on January 29, Europe/Paris is CET (UTC+1)
// So 15:00 local = 14:00 UTC
// The fake UTC should encode 15 in the hours
// But the test is getting 16 instead

console.log("\nTesting jsDateToIcsDate logic:");
console.log("  Input date (browser local string): 2026-01-29T15:00:00.000");
console.log("  getHours():", testDate.getHours(), "(browser local time)");
console.log("  For Europe/Paris on 2026-01-29:");
console.log("    UTC offset: +0100 (CET)");
console.log("    15:00 local = 14:00 UTC");
console.log("    Fake UTC should have getUTCHours() = 15");
console.log("  But test is getting: 16");
console.log("  This suggests 1 hour extra offset is being applied");
console.log("\nPossible cause:");
console.log("  The browser is in CEST (UTC+2) timezone");
console.log('  The string "2026-01-29T15:00:00.000" is parsed as 15:00 CEST');
console.log("  Which is 13:00 UTC");
console.log("  Then converted to Paris winter time (UTC+1): 14:00 Paris");
console.log("  Then encoded as fake UTC hours: 14");
console.log("  But wait - that would be 14, not 16...");
console.log("\nActual flow:");
console.log('  1. Parse "2026-01-29T15:00:00.000" in browser local (CEST): 15:00 CEST = 13:00 UTC');
console.log("  2. Convert 13:00 UTC to Europe/Paris: 14:00 CET (2026-01-29 is in winter)");
console.log("  3. Encode 14 in fake UTC... but test expects 15 and gets 16");
console.log("\nWait, getHours() returns:");
const d = new Date("2026-01-29T15:00:00.000");
console.log("  ", d.getHours(), "- this is browser local hours");
