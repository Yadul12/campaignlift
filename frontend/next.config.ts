import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  outputFileTracingIncludes: {
    "/api/**": ["./src/data/snapshot/**/*"],
  },
};

export default nextConfig;
