const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

// Sets cookie; the authentication flow uses it to maintain browser session state.
function setCookie(name: string, value: string, maxAgeSeconds = COOKIE_MAX_AGE_SECONDS) {
  document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; Max-Age=${maxAgeSeconds}; SameSite=Lax`;
}

// Clears cookie; the authentication flow uses it to maintain browser session state.
function clearCookie(name: string) {
  document.cookie = `${name}=; Path=/; Max-Age=0; SameSite=Lax`;
}

// Persists session cookies; the authentication flow uses it to maintain browser session state.
export function persistSessionCookies(accessToken: string, role: string) {
  setCookie("chat_access_token", accessToken);
  setCookie("chat_user_role", role);
}

// Clears session cookies; the authentication flow uses it to maintain browser session state.
export function clearSessionCookies() {
  clearCookie("chat_access_token");
  clearCookie("chat_user_role");
}

