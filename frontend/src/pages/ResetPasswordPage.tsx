import { FormEvent, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { CheckCircle2, LinkIcon } from 'lucide-react'
import { api } from '../api/client'
import { Button } from '../components/ui/Button'
import { Field } from '../components/ui/Field'
import { PasswordInput } from '../components/ui/PasswordInput'
import { PasswordStrength } from '../components/ui/PasswordStrength'
import { Alert } from '../components/ui/Alert'
import { AuthFrame } from '../components/AuthFrame'

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const [checking, setChecking] = useState(true)
  const [valid, setValid] = useState(false)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!token) {
      setChecking(false)
      setValid(false)
      return
    }
    api
      .resetPasswordStatus(token)
      .then((res) => setValid(res.valid))
      .catch(() => setValid(false))
      .finally(() => setChecking(false))
  }, [token])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    setSubmitting(true)
    try {
      await api.resetPassword({ token, password })
      setDone(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reset password')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthFrame title="Choose a new password" subtitle="This link is valid for one hour after it was sent.">
      {error && (
        <div className="mb-4">
          <Alert variant="error">{error}</Alert>
        </div>
      )}
      {checking && <p className="text-sm text-[color:var(--color-text-muted)]">Checking this reset link…</p>}
      {!checking && done && (
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="grid h-14 w-14 place-items-center rounded-full bg-positive-dim text-positive">
            <CheckCircle2 className="h-7 w-7" aria-hidden="true" />
          </span>
          <p className="font-display text-xl font-semibold">Your password is updated</p>
          <p className="text-sm text-[color:var(--color-text-muted)]">You were signed out everywhere, so sign in again with the new one.</p>
          <Link
            to="/login"
            className="mt-2 inline-flex w-full items-center justify-center btn-primary interactive rounded-xl px-4 py-2.5 text-sm font-semibold"
          >
            Sign in
          </Link>
        </div>
      )}
      {!checking && !done && !valid && (
        <div className="flex flex-col items-center gap-3 text-center">
          <span className="grid h-14 w-14 place-items-center rounded-full bg-warning-dim text-warning">
            <LinkIcon className="h-6 w-6" aria-hidden="true" />
          </span>
          <p className="font-display text-xl font-semibold">This link no longer works</p>
          <p className="text-sm text-[color:var(--color-text-muted)]">A reset link is good for one hour and for one use. Ask for a new one from the sign-in page.</p>
          <Link to="/login" className="mt-2 inline-flex w-full items-center justify-center btn-primary interactive rounded-xl px-4 py-2.5 text-sm font-semibold">
            Back to sign in
          </Link>
        </div>
      )}
      {!checking && !done && valid && (
        <form onSubmit={handleSubmit} className="space-y-4" autoComplete="off">
          <Field label="New password">
            <PasswordInput
              autoFocus
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          <Field label="Confirm new password">
            <PasswordInput
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </Field>
          <PasswordStrength password={password} confirm={confirm} />
          <Button type="submit" size="lg" loading={submitting} className="w-full">
            Update password
          </Button>
        </form>
      )}
    </AuthFrame>
  )
}
