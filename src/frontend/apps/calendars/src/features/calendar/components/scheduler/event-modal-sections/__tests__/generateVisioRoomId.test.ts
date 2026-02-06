import { generateVisioRoomId } from "../generateVisioRoomId";

describe("generateVisioRoomId", () => {
  it("returns a string matching the xxx-xxxx-xxx format", () => {
    const id = generateVisioRoomId();
    expect(id).toMatch(/^[a-z]{3}-[a-z]{4}-[a-z]{3}$/);
  });

  it("generates different IDs on subsequent calls", () => {
    const ids = new Set(
      Array.from({ length: 20 }, () => generateVisioRoomId()),
    );
    expect(ids.size).toBeGreaterThan(1);
  });

  it("has exactly 12 characters (3 + 1 + 4 + 1 + 3)", () => {
    const id = generateVisioRoomId();
    expect(id.length).toBe(12);
  });
});
