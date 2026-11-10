import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const apiUrl =
      process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
    // Strip /api/v1 prefix from the proxy target base
    const backendBase = apiUrl.replace(/\/api\/v1\/?$/, "");

    return [
      // Proxy all /api/* requests to the Django backend
      {
        source: "/api/:path*",
        destination: `${backendBase}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
