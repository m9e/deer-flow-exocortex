import { NextResponse, type NextRequest } from "next/server";

const DISPLAY_NAME_HEADERS = [
  "x-kamiwaza-user-name",
  "x-kamiwaza-username",
  "x-kamiwaza-user",
  "x-auth-request-preferred-username",
  "x-auth-request-user",
  "x-auth-request-email",
  "x-user-name",
  "x-user-email",
  "x-forwarded-preferred-username",
  "x-forwarded-user",
  "x-forwarded-email",
  "x-remote-user",
  "remote-user",
  "x-user",
  "x-username",
  "x-user-id",
];

function titleCase(value: string) {
  return value.replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

function displayNameFromHeader(rawValue: string | null) {
  if (!rawValue) {
    return null;
  }

  const firstValue = rawValue.split(",")[0]?.trim();
  if (!firstValue) {
    return null;
  }

  let decoded = firstValue;
  try {
    decoded = decodeURIComponent(firstValue);
  } catch {
    decoded = firstValue;
  }

  const emailLocalPart = decoded.includes("@")
    ? (decoded.split("@")[0] ?? decoded)
    : decoded;
  const normalized = emailLocalPart.replace(/[._-]+/g, " ").trim();
  return normalized ? titleCase(normalized) : null;
}

export function GET(request: NextRequest) {
  for (const headerName of DISPLAY_NAME_HEADERS) {
    const displayName = displayNameFromHeader(request.headers.get(headerName));
    if (displayName) {
      return NextResponse.json({ user: { displayName } });
    }
  }

  return NextResponse.json({ user: { displayName: null } });
}
