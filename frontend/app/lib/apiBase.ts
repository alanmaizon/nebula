const DEFAULT_API_BASE = "/api";

function normalizeTrailingSlash(value: string): string {
  if (value === "/") {
    return value;
  }
  return value.replace(/\/+$/, "");
}

export function resolveApiBase(
  configuredBase: string | null | undefined,
  pageProtocol?: string
): string {
  const rawValue = (configuredBase ?? "").trim();
  const candidate = rawValue || DEFAULT_API_BASE;

  if (candidate.startsWith("/")) {
    const normalized = normalizeTrailingSlash(candidate);
    if (normalized !== DEFAULT_API_BASE) {
      throw new Error(
        `Invalid NEXT_PUBLIC_API_BASE '${candidate}'. Use '/api' for same-origin API routing or an absolute https:// URL.`
      );
    }
    return normalized;
  }

  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error(
      `Invalid NEXT_PUBLIC_API_BASE '${candidate}'. Use '/api' for same-origin API routing or an absolute https:// URL.`
    );
  }

  const protocol = parsed.protocol.toLowerCase();
  if (protocol !== "https:" && protocol !== "http:") {
    throw new Error(
      `Invalid NEXT_PUBLIC_API_BASE '${candidate}'. Only '/api' or absolute http(s) URLs are supported.`
    );
  }

  if (protocol === "http:" && pageProtocol === "https:") {
    throw new Error(
      "Invalid NEXT_PUBLIC_API_BASE: insecure http:// API base cannot be used from an HTTPS page. Set NEXT_PUBLIC_API_BASE to '/api' or an https:// endpoint."
    );
  }

  parsed.pathname = normalizeTrailingSlash(parsed.pathname);
  parsed.search = "";
  parsed.hash = "";
  const normalized = parsed.toString();
  return normalized.endsWith("/") ? normalized.slice(0, -1) : normalized;
}

export function buildApiUrl(apiBase: string, path: string): string {
  if (!path.startsWith("/")) {
    throw new Error(`API path must start with '/': received '${path}'`);
  }
  const normalizedBase = normalizeTrailingSlash(apiBase);
  if (normalizedBase === "/") {
    return path;
  }
  return `${normalizedBase}${path}`;
}
