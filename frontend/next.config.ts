import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(process.env.DOCKER_BUILD === "true" ? { output: "standalone" } : {}),
  outputFileTracingIncludes: {
    "/api/**": ["./src/data/snapshot/**/*"],
  },
};

export default nextConfig;
