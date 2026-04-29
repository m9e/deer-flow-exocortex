import { env } from "@/env";

function getRuntimeAppBasePathFromLocation() {
  if (typeof window === "undefined") {
    return "";
  }

  return window.location.pathname.match(/^(\/runtime\/apps\/[^/]+)/)?.[1] ?? "";
}

export function getAppBasePath() {
  const basePath = env.NEXT_PUBLIC_APP_BASE_PATH?.replace(/\/+$/, "") ?? "";
  if (basePath) {
    return basePath.startsWith("/") ? basePath : `/${basePath}`;
  }
  return getRuntimeAppBasePathFromLocation();
}

function getBaseOrigin() {
  if (typeof window !== "undefined") {
    return window.location.origin;
  }
  // Fallback for SSR
  return "http://localhost:2026";
}

function getAppOriginPath() {
  return `${getBaseOrigin()}${getAppBasePath()}`;
}

export function getBackendBaseURL() {
  if (env.NEXT_PUBLIC_BACKEND_BASE_URL) {
    return new URL(env.NEXT_PUBLIC_BACKEND_BASE_URL, getBaseOrigin())
      .toString()
      .replace(/\/+$/, "");
  } else {
    return getAppBasePath();
  }
}

export function getLangGraphBaseURL(isMock?: boolean) {
  if (env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
    return new URL(
      env.NEXT_PUBLIC_LANGGRAPH_BASE_URL,
      getBaseOrigin(),
    ).toString();
  } else if (isMock) {
    if (typeof window !== "undefined") {
      return `${window.location.origin}/mock/api`;
    }
    return "http://localhost:3000/mock/api";
  } else {
    // LangGraph SDK requires a full URL, construct it from current origin
    if (typeof window !== "undefined") {
      return `${getAppOriginPath()}/api/langgraph`;
    }
    // Fallback for SSR
    return `${getAppOriginPath()}/api/langgraph`;
  }
}

export function getAppStorageNamespace() {
  return getAppBasePath() || "/";
}

export function getAppStorageKey(key: string) {
  return `deerflow:${getAppStorageNamespace()}:${key}`;
}

export function withAppBasePath(path: string) {
  if (!path.startsWith("/")) {
    return path;
  }

  const basePath = getAppBasePath();
  if (!basePath || path === basePath || path.startsWith(`${basePath}/`)) {
    return path;
  }
  return `${basePath}${path}`;
}

export function getAppCookiePath() {
  return getAppBasePath() || "/";
}
