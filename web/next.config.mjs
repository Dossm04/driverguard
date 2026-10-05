/** @type {import('next').NextConfig} */

// Security-заголовки для панели и PWA (PRODUCTION_STANDARDS 5). CSP пока не включён:
// MediaPipe (WASM с CDN + модель с Google Storage), тайлы OSM и inline-скрипты Next требуют
// точной политики — черновик в docs/ARCHITECTURE.md. Камера и геолокация — только своему origin.
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(self), microphone=(), geolocation=(self), payment=(), usb=()",
  },
];

const nextConfig = {
  outputFileTracingRoot: process.cwd(),
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    const backend = process.env.INTERNAL_API_ORIGIN || "http://127.0.0.1:8000";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/ws/:path*", destination: `${backend}/ws/:path*` },
    ];
  },
  async headers() {
    return [{ source: "/(.*)", headers: securityHeaders }];
  },
};

export default nextConfig;
