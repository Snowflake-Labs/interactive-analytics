import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // SPCS runs the app behind its own ingress; a standalone bundle keeps the
  // runtime image small.
  output: 'standalone',
  reactStrictMode: true,

  webpack: (config) => {
    // vega pulls in node-canvas for server-side rendering. The cohort heatmap is
    // rendered client-side only, so the dependency is genuinely optional and
    // resolving it to false silences an otherwise unavoidable build warning.
    config.resolve.alias = { ...config.resolve.alias, canvas: false };
    return config;
  },
};

export default nextConfig;
