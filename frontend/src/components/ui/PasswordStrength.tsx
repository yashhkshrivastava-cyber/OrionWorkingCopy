import { Check, X } from 'lucide-react'

/** How strong a new password looks, from 0 to 4. Under 8 characters is never more than 1 (the server refuses it). Only a hint: the server decides what is allowed. */
export function strengthOf(password: string): number {
  if (!password) return 0
  const points = [password.length >= 8, password.length >= 12, /[a-z]/.test(password) && /[A-Z]/.test(password), /\d/.test(password), /[^A-Za-z0-9]/.test(password)].filter(Boolean).length
  const score = Math.min(4, points)
  return password.length < 8 ? Math.min(1, score) : Math.max(2, score)
}

const LABELS = ['', 'Too short or too simple', 'Fair', 'Good', 'Strong']
const TONES = ['', 'bg-negative', 'bg-warning', 'bg-positive', 'bg-positive']

/**
 * A four-step meter under a new password, in words, and (when a second copy is typed) whether the two match. It never blocks anything: it tells
 * the person what the server would refuse (under 8 characters) and what makes a password harder to guess.
 */
export function PasswordStrength({ password, confirm }: { password: string; confirm?: string }) {
  const score = strengthOf(password)
  const showMatch = confirm !== undefined && confirm.length > 0
  const matches = password === confirm
  return (
    <div className="space-y-1.5" aria-live="polite">
      {password && (
        <>
          <div className="flex gap-1.5" role="img" aria-label={`Password strength: ${LABELS[score]}`}>
            {[1, 2, 3, 4].map((step) => (
              <span key={step} className={`h-1.5 flex-1 rounded-full transition-colors ${step <= score ? TONES[score] : 'bg-muted'}`} />
            ))}
          </div>
          <p className="t-caption text-[color:var(--color-text-muted)]">
            {LABELS[score]}
            {password.length < 8 ? ` · ${8 - password.length} more character${8 - password.length === 1 ? '' : 's'} needed` : score < 4 ? ' · a longer one with capitals, numbers and symbols is stronger' : ''}
          </p>
        </>
      )}
      {showMatch && (
        <p className={`t-caption flex items-center gap-1 font-medium ${matches ? 'text-positive' : 'text-negative'}`}>
          {matches ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : <X className="h-3.5 w-3.5" aria-hidden="true" />}
          {matches ? 'The two match' : 'The two do not match yet'}
        </p>
      )}
    </div>
  )
}
