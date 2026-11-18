// Server-side only (imported from app/api/* route handlers, never from a
// client component) -- this is what keeps GATEWAY_API_KEY out of the browser.
export function gatewayUrl(path: string): string {
  const base = process.env.GATEWAY_URL ?? "http://localhost:8000";
  return `${base}${path}`;
}

export function gatewayHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const key = process.env.GATEWAY_API_KEY;
  if (!key) {
    throw new Error("GATEWAY_API_KEY is not set (apps/web/.env.local)");
  }
  return { "X-API-Key": key, ...extra };
}
