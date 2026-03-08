import type { Config } from "jest";

const config: Config = {
  preset: "ts-jest",
  testEnvironment: "node",
  roots: ["<rootDir>/src"],
  testMatch: ["**/__tests__/**/*.test.ts", "**/__tests__/**/*.test.tsx"],
  moduleNameMapper: {
    // Handle static assets FIRST (before path aliases)
    "\\.(css|less|scss|sass|svg|png|jpg|jpeg|gif)$":
      "<rootDir>/__mocks__/fileMock.js",
    // Path aliases (mirrors tsconfig.json paths)
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  transform: {
    "^.+\\.(ts|tsx)$": [
      "ts-jest",
      {
        tsconfig: {
          jsx: "react",
          moduleResolution: "node",
        },
      },
    ],
  },
  transformIgnorePatterns: ["node_modules/(?!(.*\\.mjs$))"],
  moduleFileExtensions: ["ts", "tsx", "js", "jsx", "json", "svg"],
  collectCoverageFrom: [
    "src/**/*.{ts,tsx}",
    "!src/**/*.d.ts",
    "!src/**/__tests__/**",
  ],
};

export default config;
