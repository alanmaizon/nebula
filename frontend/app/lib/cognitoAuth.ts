export type CognitoClientConfig = {
  domain: string;
  clientId: string;
  redirectUri: string;
  logoutRedirectUri: string;
  scope: string;
};

type StoredCognitoSession = {
  accessToken: string;
  idToken: string | null;
  refreshToken: string | null;
  expiresAtEpochMs: number;
};

type StoredPkceState = {
  verifier: string;
  state: string;
};

const STORAGE_SESSION_KEY = "nebula.cognito.session";
const STORAGE_PKCE_KEY = "nebula.cognito.pkce";

function toBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const value of bytes) {
    binary += String.fromCharCode(value);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function randomBase64Url(byteCount: number): string {
  const bytes = new Uint8Array(byteCount);
  crypto.getRandomValues(bytes);
  return toBase64Url(bytes);
}

async function computePkceCodeChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return toBase64Url(new Uint8Array(digest));
}

function normalizeDomain(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error("NEXT_PUBLIC_COGNITO_DOMAIN is required when auth is enabled.");
  }
  if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
    const parsed = new URL(trimmed);
    return parsed.host;
  }
  return trimmed;
}

function persistPkceState(state: StoredPkceState): void {
  sessionStorage.setItem(STORAGE_PKCE_KEY, JSON.stringify(state));
}

function readPkceState(): StoredPkceState | null {
  const raw = sessionStorage.getItem(STORAGE_PKCE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as StoredPkceState;
    if (typeof parsed.verifier === "string" && typeof parsed.state === "string") {
      return parsed;
    }
  } catch {
    return null;
  }
  return null;
}

function clearPkceState(): void {
  sessionStorage.removeItem(STORAGE_PKCE_KEY);
}

function persistSession(session: StoredCognitoSession): void {
  localStorage.setItem(STORAGE_SESSION_KEY, JSON.stringify(session));
}

export function clearStoredCognitoSession(): void {
  localStorage.removeItem(STORAGE_SESSION_KEY);
}

export function getStoredAccessToken(): string | null {
  const raw = localStorage.getItem(STORAGE_SESSION_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as StoredCognitoSession;
    if (!parsed.accessToken || !parsed.expiresAtEpochMs || Date.now() >= parsed.expiresAtEpochMs) {
      clearStoredCognitoSession();
      return null;
    }
    return parsed.accessToken;
  } catch {
    clearStoredCognitoSession();
    return null;
  }
}

function boolFromEnv(value: string | undefined): boolean {
  return typeof value === "string" && value.trim().toLowerCase() === "true";
}

export function readCognitoClientConfig(): CognitoClientConfig | null {
  if (!boolFromEnv(process.env.NEXT_PUBLIC_AUTH_ENABLED)) {
    return null;
  }
  const domain = normalizeDomain(process.env.NEXT_PUBLIC_COGNITO_DOMAIN ?? "");
  const clientId = (process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID ?? "").trim();
  const redirectUri = (process.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI ?? "").trim();
  const logoutRedirectUri = (process.env.NEXT_PUBLIC_COGNITO_LOGOUT_REDIRECT_URI ?? "").trim();
  const scope = (process.env.NEXT_PUBLIC_COGNITO_SCOPE ?? "openid email profile").trim();

  if (!clientId) {
    throw new Error("NEXT_PUBLIC_COGNITO_CLIENT_ID is required when auth is enabled.");
  }
  if (!redirectUri) {
    throw new Error("NEXT_PUBLIC_COGNITO_REDIRECT_URI is required when auth is enabled.");
  }

  return {
    domain,
    clientId,
    redirectUri,
    logoutRedirectUri: logoutRedirectUri || redirectUri,
    scope,
  };
}

export async function beginCognitoLogin(config: CognitoClientConfig): Promise<void> {
  const state = randomBase64Url(24);
  const verifier = randomBase64Url(64);
  const codeChallenge = await computePkceCodeChallenge(verifier);
  persistPkceState({ state, verifier });

  const authorizeUrl = new URL(`https://${config.domain}/oauth2/authorize`);
  authorizeUrl.searchParams.set("response_type", "code");
  authorizeUrl.searchParams.set("client_id", config.clientId);
  authorizeUrl.searchParams.set("redirect_uri", config.redirectUri);
  authorizeUrl.searchParams.set("scope", config.scope);
  authorizeUrl.searchParams.set("state", state);
  authorizeUrl.searchParams.set("code_challenge_method", "S256");
  authorizeUrl.searchParams.set("code_challenge", codeChallenge);

  window.location.assign(authorizeUrl.toString());
}

export async function completeCognitoLoginIfPresent(config: CognitoClientConfig): Promise<boolean> {
  const url = new URL(window.location.href);
  const error = url.searchParams.get("error");
  if (error) {
    const description = url.searchParams.get("error_description");
    throw new Error(description ? `${error}: ${description}` : error);
  }

  const code = url.searchParams.get("code");
  if (!code) {
    return false;
  }
  const returnedState = url.searchParams.get("state");
  const pkce = readPkceState();
  if (!pkce || !returnedState || pkce.state !== returnedState) {
    clearPkceState();
    throw new Error("Cognito callback state validation failed. Please try signing in again.");
  }

  const body = new URLSearchParams();
  body.set("grant_type", "authorization_code");
  body.set("client_id", config.clientId);
  body.set("code", code);
  body.set("redirect_uri", config.redirectUri);
  body.set("code_verifier", pkce.verifier);

  const response = await fetch(`https://${config.domain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const payload = (await response.json()) as {
    access_token?: string;
    id_token?: string;
    refresh_token?: string;
    expires_in?: number;
    error?: string;
    error_description?: string;
  };
  if (!response.ok || !payload.access_token) {
    const detail = payload.error_description || payload.error || "Token exchange failed.";
    throw new Error(`Cognito token exchange failed: ${detail}`);
  }

  const expiresIn = typeof payload.expires_in === "number" ? payload.expires_in : 3600;
  persistSession({
    accessToken: payload.access_token,
    idToken: payload.id_token ?? null,
    refreshToken: payload.refresh_token ?? null,
    expiresAtEpochMs: Date.now() + expiresIn * 1000,
  });
  clearPkceState();

  const cleaned = new URL(window.location.href);
  cleaned.searchParams.delete("code");
  cleaned.searchParams.delete("state");
  cleaned.searchParams.delete("error");
  cleaned.searchParams.delete("error_description");
  window.history.replaceState({}, document.title, cleaned.toString());
  return true;
}

export function signOutFromCognito(config: CognitoClientConfig): void {
  clearPkceState();
  clearStoredCognitoSession();
  const logoutUrl = new URL(`https://${config.domain}/logout`);
  logoutUrl.searchParams.set("client_id", config.clientId);
  logoutUrl.searchParams.set("logout_uri", config.logoutRedirectUri);
  window.location.assign(logoutUrl.toString());
}
