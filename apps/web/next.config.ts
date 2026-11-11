import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    // NEXT_PUBLIC_API_URL is a relative path used by the browser (/api/v1).
    // The rewrite destination must be an absolute URL pointing at Django.
    // Use the server-side BACKEND_URL var in production; default to localhost
    // for local development.
    const backendOrigin =
      process.env.BACKEND_URL ?? "http://localhost:8000";

    return [
      // Proxy all /api/* requests to the Django backend.
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
