import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  debug: process.env.NODE_ENV === "development",
  reactStrictMode: false,
  webpack: (config, { isServer }) => {
    // Resolve workspace packages
    config.resolve.alias = {
      ...config.resolve.alias,
      
    };
    return config;
  },
};

export default nextConfig;
