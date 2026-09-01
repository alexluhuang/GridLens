import type { CurrentUser } from "./types";

const authMode = (import.meta.env.VITE_GRIDLENS_AUTH_MODE || "none").trim().toLowerCase();
const cognitoDomain = (import.meta.env.VITE_GRIDLENS_COGNITO_DOMAIN || "").trim().replace(/\/$/, "");
const cognitoClientId = (import.meta.env.VITE_GRIDLENS_COGNITO_CLIENT_ID || "").trim();
const authStorageKey = "gridlens-auth-session";
const pkceVerifierStorageKey = "gridlens-auth-pkce-verifier";
const stateStorageKey = "gridlens-auth-state";

type StoredSession = {
  accessToken: string;
  idToken: string;
  refreshToken: string;
  expiresAt: number;
  user: CurrentUser;
};

type CognitoTokenResponse = {
  access_token: string;
  id_token: string;
  refresh_token?: string;
  expires_in: number;
  token_type: string;
};

export function isAuthEnabled() {
  return authMode === "cognito";
}

export function readStoredSession(): StoredSession | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(authStorageKey);
    if (!raw) {
      return null;
    }
    const session = JSON.parse(raw) as StoredSession;
    if (!session.accessToken || !session.idToken || !session.expiresAt) {
      return null;
    }
    if (Date.now() >= session.expiresAt) {
      clearAuthSession();
      return null;
    }
    return session;
  } catch {
    return null;
  }
}

export function getAccessToken(): string {
  return readStoredSession()?.accessToken || "";
}

export async function initializeAuthSession(): Promise<CurrentUser | null> {
  if (!isAuthEnabled() || typeof window === "undefined") {
    return null;
  }

  const callbackParams = new URLSearchParams(window.location.search);
  const code = callbackParams.get("code");
  const state = callbackParams.get("state");
  if (code && state) {
    const expectedState = window.sessionStorage.getItem(stateStorageKey);
    const verifier = window.sessionStorage.getItem(pkceVerifierStorageKey);
    if (!expectedState || expectedState !== state || !verifier) {
      throw new Error("The Cognito sign-in response could not be validated.");
    }
    const tokenResponse = await exchangeCodeForTokens(code, verifier);
    const user = parseCurrentUserFromToken(tokenResponse.id_token, tokenResponse.access_token);
    storeSession(tokenResponse, user);
    cleanupAuthCallback();
    return user;
  }

  return readStoredSession()?.user || null;
}

export async function beginSignIn() {
  if (!isAuthEnabled()) {
    return;
  }
  if (!cognitoDomain || !cognitoClientId) {
    throw new Error("Cognito frontend configuration is missing.");
  }
  const state = randomString(32);
  const verifier = randomString(64);
  const challenge = base64UrlEncode(await sha256(verifier));
  window.sessionStorage.setItem(stateStorageKey, state);
  window.sessionStorage.setItem(pkceVerifierStorageKey, verifier);
  const params = new URLSearchParams({
    client_id: cognitoClientId,
    response_type: "code",
    scope: "openid email profile",
    redirect_uri: redirectUri(),
    state,
    code_challenge_method: "S256",
    code_challenge: challenge,
  });
  window.location.assign(`${cognitoDomain}/login?${params.toString()}`);
}

export function signOut() {
  const session = readStoredSession();
  clearAuthSession();
  if (!isAuthEnabled() || !cognitoDomain || !cognitoClientId) {
    return;
  }
  const params = new URLSearchParams({
    client_id: cognitoClientId,
    logout_uri: redirectUri(),
  });
  if (session) {
    window.location.assign(`${cognitoDomain}/logout?${params.toString()}`);
  }
}

export function clearAuthSession() {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(authStorageKey);
  window.sessionStorage.removeItem(pkceVerifierStorageKey);
  window.sessionStorage.removeItem(stateStorageKey);
}

async function exchangeCodeForTokens(code: string, verifier: string): Promise<CognitoTokenResponse> {
  const response = await fetch(`${cognitoDomain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: cognitoClientId,
      code,
      code_verifier: verifier,
      redirect_uri: redirectUri(),
    }),
  });
  if (!response.ok) {
    throw new Error("Cognito token exchange failed.");
  }
  return response.json() as Promise<CognitoTokenResponse>;
}

function storeSession(tokenResponse: CognitoTokenResponse, user: CurrentUser) {
  const session: StoredSession = {
    accessToken: tokenResponse.access_token,
    idToken: tokenResponse.id_token,
    refreshToken: tokenResponse.refresh_token || "",
    expiresAt: Date.now() + Math.max(0, tokenResponse.expires_in - 30) * 1000,
    user,
  };
  window.localStorage.setItem(authStorageKey, JSON.stringify(session));
}

function parseCurrentUserFromToken(idToken: string, accessToken: string): CurrentUser {
  const idClaims = parseJwtPayload(idToken);
  const accessClaims = parseJwtPayload(accessToken);
  return {
    authenticated: true,
    subject: String(idClaims.sub || accessClaims.sub || ""),
    username: String(idClaims.email || accessClaims["cognito:username"] || accessClaims.username || ""),
    email: String(idClaims.email || ""),
  };
}

function parseJwtPayload(token: string): Record<string, unknown> {
  const parts = token.split(".");
  if (parts.length < 2) {
    throw new Error("Invalid token payload.");
  }
  const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
  const padded = payload + "=".repeat((4 - (payload.length % 4 || 4)) % 4);
  return JSON.parse(window.atob(padded)) as Record<string, unknown>;
}

function cleanupAuthCallback() {
  window.sessionStorage.removeItem(pkceVerifierStorageKey);
  window.sessionStorage.removeItem(stateStorageKey);
  const nextUrl = new URL(window.location.href);
  nextUrl.searchParams.delete("code");
  nextUrl.searchParams.delete("state");
  window.history.replaceState({}, document.title, nextUrl.toString());
}

function redirectUri() {
  return new URL(import.meta.env.BASE_URL, window.location.origin).toString();
}

function randomString(length: number) {
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return base64UrlEncode(bytes).slice(0, length);
}

async function sha256(value: string) {
  const encoder = new TextEncoder();
  const data = encoder.encode(value);
  return window.crypto.subtle.digest("SHA-256", data);
}

function base64UrlEncode(value: ArrayBuffer | Uint8Array | Promise<ArrayBuffer>) {
  if (value instanceof Promise) {
    throw new Error("Unexpected async crypto result.");
  }
  const bytes = value instanceof Uint8Array ? value : new Uint8Array(value);
  let text = "";
  for (const byte of bytes) {
    text += String.fromCharCode(byte);
  }
  return window.btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}
