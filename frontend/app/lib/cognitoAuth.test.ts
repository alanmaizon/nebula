import { afterEach, describe, expect, it } from "vitest";

import { getStoredAccessToken, readCognitoClientConfig } from "./cognitoAuth";

const ORIGINAL_ENV = { ...process.env };

function resetEnv(): void {
  process.env = { ...ORIGINAL_ENV };
}

afterEach(() => {
  resetEnv();
  localStorage.clear();
  sessionStorage.clear();
});

function toBase64Url(value: string): string {
  return btoa(value).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function buildJwt(payload: Record<string, unknown>): string {
  const header = toBase64Url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const body = toBase64Url(JSON.stringify(payload));
  return `${header}.${body}.signature`;
}

describe("readCognitoClientConfig", () => {
  it("returns null when auth is disabled", () => {
    process.env.NEXT_PUBLIC_AUTH_ENABLED = "false";
    expect(readCognitoClientConfig()).toBeNull();
  });

  it("requires a domain when auth is enabled", () => {
    process.env.NEXT_PUBLIC_AUTH_ENABLED = "true";
    process.env.NEXT_PUBLIC_COGNITO_DOMAIN = "";
    process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID = "client-1";
    process.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI = "https://app.example.com";

    expect(() => readCognitoClientConfig()).toThrow("NEXT_PUBLIC_COGNITO_DOMAIN");
  });

  it("normalizes domain and uses fallback scope/logout URI defaults", () => {
    process.env.NEXT_PUBLIC_AUTH_ENABLED = "true";
    process.env.NEXT_PUBLIC_COGNITO_DOMAIN = "https://example.auth.eu-central-1.amazoncognito.com/";
    process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID = "client-1";
    process.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI = "https://app.example.com/callback";
    delete process.env.NEXT_PUBLIC_COGNITO_LOGOUT_REDIRECT_URI;
    delete process.env.NEXT_PUBLIC_COGNITO_SCOPE;

    const config = readCognitoClientConfig();
    expect(config).toEqual({
      domain: "example.auth.eu-central-1.amazoncognito.com",
      clientId: "client-1",
      redirectUri: "https://app.example.com/callback",
      logoutRedirectUri: "https://app.example.com/callback",
      scope: "openid email profile",
    });
  });
});

describe("getStoredAccessToken", () => {
  it("returns the stored access token when the client id matches", () => {
    const token = buildJwt({ token_use: "access", client_id: "client-1" });
    localStorage.setItem(
      "nebula.cognito.session",
      JSON.stringify({
        accessToken: token,
        idToken: null,
        refreshToken: null,
        expiresAtEpochMs: Date.now() + 60_000,
      })
    );

    expect(getStoredAccessToken("client-1")).toBe(token);
  });

  it("clears the stored session when the access token client id no longer matches", () => {
    const token = buildJwt({ token_use: "access", client_id: "old-client" });
    localStorage.setItem(
      "nebula.cognito.session",
      JSON.stringify({
        accessToken: token,
        idToken: null,
        refreshToken: null,
        expiresAtEpochMs: Date.now() + 60_000,
      })
    );

    expect(getStoredAccessToken("new-client")).toBeNull();
    expect(localStorage.getItem("nebula.cognito.session")).toBeNull();
  });

  it("clears the stored session when the ID token audience no longer matches", () => {
    const token = buildJwt({ token_use: "id", aud: "old-client" });
    localStorage.setItem(
      "nebula.cognito.session",
      JSON.stringify({
        accessToken: token,
        idToken: null,
        refreshToken: null,
        expiresAtEpochMs: Date.now() + 60_000,
      })
    );

    expect(getStoredAccessToken("new-client")).toBeNull();
    expect(localStorage.getItem("nebula.cognito.session")).toBeNull();
  });
});
