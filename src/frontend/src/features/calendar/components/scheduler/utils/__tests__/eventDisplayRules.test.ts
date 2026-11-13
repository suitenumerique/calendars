import { describe, expect, it } from "vitest";

import { cleanEventForDisplay } from "../eventDisplayRules";

const URL = "https://visio.numerique.gouv.fr/abc-defg-hij";
const BLOCK = `-::~ video ~::-\n${URL}\n-::~ video ~::-`;

describe("cleanEventForDisplay", () => {
  it("removes our video link block when the url is set", () => {
    const cleaned = cleanEventForDisplay({
      description: `Weekly sync\n\n${BLOCK}`,
      location: URL,
      url: URL,
    });
    expect(cleaned).toEqual({ description: "Weekly sync", location: "", url: URL });
  });

  it("takes the url from our video link block when the url is empty", () => {
    const cleaned = cleanEventForDisplay({ description: BLOCK, location: "Room 301", url: "" });
    expect(cleaned).toEqual({ description: "", location: "Room 301", url: URL });
  });

  it("keeps a description without a block", () => {
    const cleaned = cleanEventForDisplay({ description: "Weekly sync", location: "", url: URL });
    expect(cleaned).toEqual({ description: "Weekly sync", location: "", url: URL });
  });
});
