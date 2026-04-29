/**
 * Run `build` or `dev` with `SKIP_ENV_VALIDATION` to skip env validation. This is especially useful
 * for Docker builds.
 */
import "./src/env.js";

function getInternalServiceURL(envKey, fallbackURL) {
  const configured = process.env[envKey]?.trim();
  return configured && configured.length > 0
    ? configured.replace(/\/+$/, "")
    : fallbackURL;
}
import nextra from "nextra";

const withNextra = nextra({});
const basePath = (process.env.NEXT_PUBLIC_APP_BASE_PATH || "").replace(
  /\/+$/,
  "",
);

/** @type {import("next").NextConfig} */
const config = {
  basePath: basePath || undefined,
  assetPrefix: basePath || undefined,
  skipTrailingSlashRedirect: true,
  i18n: {
    locales: ["en", "zh"],
    defaultLocale: "en",
  },
  devIndicators: false,
  async rewrites() {
    const rewrites = [];
    const langgraphURL = getInternalServiceURL(
      "DEER_FLOW_INTERNAL_LANGGRAPH_BASE_URL",
      "http://127.0.0.1:2024",
    );
    const gatewayURL = getInternalServiceURL(
      "DEER_FLOW_INTERNAL_GATEWAY_BASE_URL",
      "http://127.0.0.1:8001",
    );

    if (!process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
      rewrites.push({
        source: "/api/langgraph",
        destination: langgraphURL,
      });
      rewrites.push({
        source: "/api/langgraph/:path*",
        destination: `${langgraphURL}/:path*`,
      });
    }

    if (!process.env.NEXT_PUBLIC_BACKEND_BASE_URL) {
      rewrites.push({
        source: "/api/agents",
        destination: `${gatewayURL}/api/agents`,
      });
      rewrites.push({
        source: "/api/agents/:path*",
        destination: `${gatewayURL}/api/agents/:path*`,
      });
      rewrites.push({
        source: "/api/skills",
        destination: `${gatewayURL}/api/skills`,
      });
      rewrites.push({
        source: "/api/skills/:path*",
        destination: `${gatewayURL}/api/skills/:path*`,
      });
      rewrites.push({
        source: "/api/models",
        destination: `${gatewayURL}/api/models`,
      });
      rewrites.push({
        source: "/api/models/:path*",
        destination: `${gatewayURL}/api/models/:path*`,
      });
      rewrites.push({
        source: "/api/mcp",
        destination: `${gatewayURL}/api/mcp`,
      });
      rewrites.push({
        source: "/api/mcp/:path*",
        destination: `${gatewayURL}/api/mcp/:path*`,
      });
      rewrites.push({
        source: "/api/threads",
        destination: `${gatewayURL}/api/threads`,
      });
      rewrites.push({
        source: "/api/threads/:path*",
        destination: `${gatewayURL}/api/threads/:path*`,
      });
      rewrites.push({
        source: "/api/memory",
        destination: `${gatewayURL}/api/memory`,
      });
      rewrites.push({
        source: "/api/memory/:path*",
        destination: `${gatewayURL}/api/memory/:path*`,
      });
    }

    return rewrites;
  },
};

export default withNextra(config);
