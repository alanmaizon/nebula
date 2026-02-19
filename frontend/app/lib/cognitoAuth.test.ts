import { afterEach, describe, expect, it } from "vitest";

import { readCognitoClientConfig } from "./cognitoAuth";

const ORIGINAL_ENV = { ...process.env };

function resetEnv(): void {
  process.env = { ...ORIGINAL_ENV };
}

afterEach(() => {
  resetEnv();
});

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
