import { describe, expect, it, vi } from "vitest";

import { latestOnly } from "../latestOnly";

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
};

describe("latestOnly", () => {
  it("gives the result of the latest call when an old call ends last", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const source = latestOnly((arg: number) => (arg === 1 ? first.promise : second.promise));
    const success = vi.fn();
    const failure = vi.fn();

    source(1, success, failure);
    source(2, success, failure);
    second.resolve("new");
    first.resolve("old");
    await Promise.resolve();
    await Promise.resolve();

    expect(success).toHaveBeenCalledTimes(1);
    expect(success).toHaveBeenCalledWith("new");
    expect(failure).toHaveBeenCalledTimes(1);
  });

  it("reports a rejected call as a failure", async () => {
    const error = new Error("boom");
    const source = latestOnly(() => Promise.reject(error));
    const success = vi.fn();
    const failure = vi.fn();

    source(undefined, success, failure);
    await Promise.resolve();
    await Promise.resolve();

    expect(success).not.toHaveBeenCalled();
    expect(failure).toHaveBeenCalledWith(error);
  });
});
