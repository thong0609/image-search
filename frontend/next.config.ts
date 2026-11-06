import type { NextConfig } from "next";

const origin = new URL(process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000");
if (
  !["http:", "https:"].includes(origin.protocol) ||
  origin.username ||
  origin.password ||
  origin.pathname !== "/" ||
  origin.search ||
  origin.hash
) {
  throw new Error(
    "BACKEND_ORIGIN must be an HTTP(S) origin without credentials or path",
  );
}
const nextConfig: NextConfig = {
  poweredByHeader: false,
  async rewrites() {
    return [
      { source: "/v1/:path*", destination: `${origin.origin}/v1/:path*` },
      {
        source: "/health/:path*",
        destination: `${origin.origin}/health/:path*`,
      },
    ];
  },
};
export default nextConfig;
