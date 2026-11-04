import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { BillCard } from '../types'

/**
 * Bill cards, fetched when someone first points at a bill number and kept for a short while, so moving the pointer along a column of
 * bills (or back to one) does not ask the server again for each. Short, because a payment can be recorded at any moment and the card
 * says what has been received.
 */
const KEEP_MS = 30_000
const KEEP_FAILURE_MS = 5_000

type Entry = { at: number; ttl: number; value: Promise<BillCard | null> }
const cache = new Map<string, Entry>()

export type BillRef = { number?: string | null; code?: string | null }

const keyOf = (ref: BillRef): string | null => (ref.code ? `code:${ref.code}` : ref.number ? `number:${ref.number}` : null)

/** The card, or null when there is no such bill. A failure to reach the server rejects, and is remembered only briefly. */
export function fetchBillCard(ref: BillRef): Promise<BillCard | null> {
  const key = keyOf(ref)
  if (!key) return Promise.resolve(null)
  const now = Date.now()
  const known = cache.get(key)
  if (known && now - known.at < known.ttl) return known.value

  const value = api
    .billCard({ code: ref.code ?? undefined, number: ref.number ?? undefined })
    .then((card): BillCard | null => {
      // Whichever way it was asked for, it can be found either way next time.
      const later = Date.now()
      cache.set(`code:${card.id}`, { at: later, ttl: KEEP_MS, value: Promise.resolve(card) })
      cache.set(`number:${card.bill_number}`, { at: later, ttl: KEEP_MS, value: Promise.resolve(card) })
      return card
    })
    .catch((error: unknown) => {
      if (error instanceof ApiError && error.status === 404) return null
      cache.delete(key)
      throw error
    })
  cache.set(key, { at: now, ttl: KEEP_MS, value })
  void value.catch(() => cache.set(key, { at: Date.now(), ttl: KEEP_FAILURE_MS, value }))
  return value
}

export type BillCardState =
  | { state: 'idle' }
  | { state: 'loading' }
  | { state: 'ready'; card: BillCard }
  | { state: 'missing' }
  | { state: 'error'; message: string }

/** The card for a bill, once `enabled` (the card is open). */
export function useBillCard(ref: BillRef, enabled: boolean): BillCardState {
  const [result, setResult] = useState<{ key: string; value: BillCardState } | null>(null)
  const key = keyOf(ref)

  useEffect(() => {
    if (!enabled || !key) return
    let current = true
    fetchBillCard({ code: ref.code, number: ref.number })
      .then((card) => current && setResult({ key, value: card ? { state: 'ready', card } : { state: 'missing' } }))
      .catch((error: Error) => current && setResult({ key, value: { state: 'error', message: error.message } }))
    return () => {
      current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the pair (code, number) is the key
  }, [enabled, key])

  if (!enabled || !key) return { state: 'idle' }
  return result && result.key === key ? result.value : { state: 'loading' }
}

/** For tests: forget everything. */
export function forgetBillCards(): void {
  cache.clear()
}
