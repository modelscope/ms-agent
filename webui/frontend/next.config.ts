import type { NextConfig } from "next";

// Static export mode for production deployment
const isStaticExport = process.env.NEXT_BUILD_STATIC === "true";

const nextConfig: NextConfig = {
  // Enable React Compiler
  reactCompiler: true,

  // Static export configuration
  ...(isStaticExport && {
    output: "export",
    images: {
      unoptimized: true,
    },
  }),

  // Dev indicator position
  devIndicators: {
    position: "bottom-right",
  },
};

export default nextConfig;
