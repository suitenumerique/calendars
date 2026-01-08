import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  output: "export",
  debug: process.env.NODE_ENV === "development",
  reactStrictMode: false,
  webpack: (config, { isServer }) => {
    // Resolve workspace packages
    config.resolve.alias = {
      ...config.resolve.alias,
      "open-dav-calendar": path.resolve(
        __dirname,
        "../../packages/open-calendar/dist/index.js"
      ),
    };
    return config;
  },
};

export default nextConfig;
