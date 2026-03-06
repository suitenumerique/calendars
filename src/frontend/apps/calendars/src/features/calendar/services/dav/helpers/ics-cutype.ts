/**
 * Post-processes an ICS string to inject CUTYPE parameters for resource attendees.
 *
 * ts-ics does not support the CUTYPE property on attendees. This function
 * injects CUTYPE=ROOM or CUTYPE=RESOURCE into ATTENDEE lines whose
 * mailto: address matches a known resource email, ensuring RFC 5545
 * compliance and interoperability with other CalDAV clients.
 */
export function injectCutype(
  icsString: string,
  resourceEmails: Map<string, "ROOM" | "RESOURCE">,
): string {
  if (resourceEmails.size === 0) return icsString;

  // Build a lowercase lookup for case-insensitive matching
  const lookup = new Map<string, "ROOM" | "RESOURCE">();
  for (const [email, cutype] of resourceEmails) {
    lookup.set(email.toLowerCase(), cutype);
  }

  return icsString.replace(
    /^(ATTENDEE)((?:;[^\r\n:]+)*):mailto:([^\r\n]+)$/gm,
    (match, prefix: string, params: string, email: string) => {
      const cutype = lookup.get(email.toLowerCase());
      if (!cutype) return match;

      // Don't inject if CUTYPE is already present
      if (/;CUTYPE=/i.test(params)) return match;

      return `${prefix};CUTYPE=${cutype}${params}:mailto:${email}`;
    },
  );
}
