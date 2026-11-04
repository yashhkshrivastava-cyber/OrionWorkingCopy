/**
 * A random key for ONE submission of a form, sent as `Idempotency-Key`. The server saves the bill or payment and the key in the
 * same transaction, so if the same request arrives again (a double-click, a retry after the connection dropped, a stale tab) it is
 * answered with the first result instead of being saved twice.
 *
 * Make one when the form opens and keep it for every attempt at that form; make a new one for the next form. Never make one per
 * click: that is exactly what it exists to prevent.
 *
 * `crypto.randomUUID` only exists on https and localhost, and the office LAN is plain http, so it falls back to random bytes.
 * The shape must match the server's: 8 to 100 of letters, digits, `.`, `_`, `:` and `-`.
 */
export function newIdempotencyKey(): string {
  const c: Crypto | undefined = typeof crypto === 'undefined' ? undefined : crypto
  if (c && typeof c.randomUUID === 'function') return c.randomUUID()
  const bytes = new Uint8Array(16)
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(bytes)
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256)
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

/** The header for a request that carries a key; nothing when there is none. */
export function idempotencyHeader(key?: string): Record<string, string> {
  return key ? { 'Idempotency-Key': key } : {}
}
