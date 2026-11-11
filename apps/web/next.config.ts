import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Do NOT let Next.js strip or add trailing slashes to URLs — Django's
  // CommonMiddleware requires them and will 500 on a POST if they are missing.
  trailingSlash: false,
  skipTrailingSlashRedirect: true,

  async rewrites() {
    // NEXT_PUBLIC_API_URL is a relative path used by the browser (/api/v1).
    // The rewrite destination must be an absolute URL pointing at Django.
    // Use the server-side BACKEND_URL var in production; default to localhost
    // for local development.
    const backendOrigin =
      process.env.BACKEND_URL ?? "http://localhost:8000";

    return [
      // Proxy /api/... including the trailing slash Django requires.
      // The :path* wildcard preserves whatever the client sends verbatim.
      {
        source: "/api/:path*/",
        destination: `${backendOrigin}/api/:path*/`,
      },
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
