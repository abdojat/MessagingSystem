const CSRF_COOKIE_NAMES = ["__Host-messaging_csrf", "messaging_csrf"] as const;

export interface BrowserAccessTokenResponse {
  access_token: string;
  token_type: "bearer";
}

function readCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  const cookies = document.cookie.split(";");
  for (const cookieName of CSRF_COOKIE_NAMES) {
    const prefix = `${cookieName}=`;
    const match = cookies.map((value) => value.trim()).find((value) => value.startsWith(prefix));
    if (match) return decodeURIComponent(match.slice(prefix.length));
  }
  return null;
}

async function csrfToken(baseUrl: string): Promise<string> {
  const existing = readCsrfCookie();
  if (existing) return existing;

  const response = await fetch(`${baseUrl}/auth/browser/csrf`, {
    method: "GET",
    credentials: "include",
  });
  if (!response.ok) throw new Error("Unable to establish CSRF state");
  const data = (await response.json()) as { csrf_token?: string };
  if (!data.csrf_token) throw new Error("CSRF response was incomplete");
  return data.csrf_token;
}

export async function browserRefreshRequest(baseUrl: string): Promise<Response> {
  const csrf = await csrfToken(baseUrl);
  return fetch(`${baseUrl}/auth/browser/refresh`, {
    method: "POST",
    credentials: "include",
    headers: { "X-CSRF-Token": csrf },
  });
}

export async function browserLogoutRequest(baseUrl: string): Promise<Response> {
  const csrf = await csrfToken(baseUrl);
  return fetch(`${baseUrl}/auth/browser/logout`, {
    method: "POST",
    credentials: "include",
    headers: { "X-CSRF-Token": csrf },
  });
}
