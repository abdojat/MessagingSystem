const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

function setCookie(name: string, value: string, maxAgeSeconds = COOKIE_MAX_AGE_SECONDS) {
  document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; Max-Age=${maxAgeSeconds}; SameSite=Lax`;
}

function clearCookie(name: string) {
  document.cookie = `${name}=; Path=/; Max-Age=0; SameSite=Lax`;
}

export function persistSessionCookies(accessToken: string, role: string) {
  setCookie("chat_access_token", accessToken);
  setCookie("chat_user_role", role);
}

export function clearSessionCookies() {
  clearCookie("chat_access_token");
  clearCookie("chat_user_role");
}

