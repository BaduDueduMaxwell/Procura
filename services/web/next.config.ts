import type { NextConfig } from "next";
const securityHeaders = [
  { key: "Content-Security-Policy", value: "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' http://localhost:8000; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];
const apiOrigin = process.env.API_ORIGIN?.replace(/\/$/, "");
const nextConfig: NextConfig = { output: "standalone", reactStrictMode: true, poweredByHeader: false, turbopack: { root: process.cwd() }, agentRules: false, async headers() { return [{ source: "/:path*", headers: securityHeaders }]; }, async rewrites() { return apiOrigin ? [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }] : []; } };
export default nextConfig;
