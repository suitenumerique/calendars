import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const roots = new Set<Root>();

// Unmount every root after each test, so no state or effect leaks into
// the next test.
afterEach(() => {
  act(() => roots.forEach((root) => root.unmount()));
  roots.clear();
});

/** Renders a hook in a probe component. `current` holds its last return value. */
export const renderHook = <T>(useHook: () => T) => {
  const result = { current: null as unknown as T };
  const Probe = () => {
    result.current = useHook();
    return null;
  };
  const root = createRoot(document.createElement("div"));
  roots.add(root);
  act(() => root.render(createElement(Probe)));
  return result;
};
