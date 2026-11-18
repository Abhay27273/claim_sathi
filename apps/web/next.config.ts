import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Multi-document uploads can exceed the 1MB default body-size limit for
  // Server Actions / route handlers in some Next.js versions.
  experimental: {
    serverActions: {
      bodySizeLimit: "20mb",
    },
  },
};

export default nextConfig;
