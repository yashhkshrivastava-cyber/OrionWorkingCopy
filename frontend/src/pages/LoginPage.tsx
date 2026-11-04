import { FormEvent, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { Lock, Mail, Phone, User } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { api } from '../api/client'
import { Button } from '../components/ui/Button'
import { Field, Input } from '../components/ui/Field'
import { PasswordInput } from '../components/ui/PasswordInput'
import { PasswordStrength } from '../components/ui/PasswordStrength'
import { Alert } from '../components/ui/Alert'
import { AuthFrame } from '../components/AuthFrame'

type Mode = 'signin' | 'reset' | 'register'

const emptyRegister = () => ({
  username: '',
  display_name: '',
  email: '',
  phone: '',
  password: '',
  confirm: '',
})

export function LoginPage() {
  const { user, login } = useAuth()
  const [mode, setMode] = useState<Mode>('signin')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [resetEmail, setResetEmail] = useState('')
  const [successMessage, setSuccessMessage] = useState('')
  const [registerForm, setRegisterForm] = useState(emptyRegister)

  if (user) return <Navigate to="/" replace />

  const switchMode = (next: Mode) => {
    setMode(next)
    setError('')
    setSuccessMessage('')
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password) {
      setError('Enter both username and password.')
      return
    }
    setSubmitting(true)
    try {
      await login(username.trim(), password)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Login failed'
      setError(
        /failed to fetch|networkerror|load failed/i.test(message)
          ? 'Cannot reach the API. Start it with scripts/start-api.ps1, then try again.'
          : message,
      )
    } finally {
      setSubmitting(false)
    }
  }

  const handleReset = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setSuccessMessage('')
    if (!username.trim() || !resetEmail.trim()) {
      setError('Enter your username and the email on your account.')
      return
    }
    setSubmitting(true)
    try {
      await api.forgotPassword({
        username: username.trim(),
        email: resetEmail.trim(),
      })
      setSuccessMessage(
        'If that account exists, we sent a reset link. Check your email and open the link within one hour.',
      )
      setMode('signin')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not send reset email')
    } finally {
      setSubmitting(false)
    }
  }

  const handleRegister = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setSuccessMessage('')
    if (registerForm.password !== registerForm.confirm) {
      setError('Passwords do not match.')
      return
    }
    setSubmitting(true)
    try {
      await api.register({
        username: registerForm.username.trim(),
        display_name: registerForm.display_name.trim(),
        password: registerForm.password,
        email: registerForm.email.trim(),
        phone: registerForm.phone.trim() || undefined,
      })
      setRegisterForm(emptyRegister())
      setUsername(registerForm.username.trim())
      setSuccessMessage(
        'Request submitted. An administrator will review it, then you will get an email when the account is ready.',
      )
      setMode('signin')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not submit the request')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthFrame
      title={mode === 'register' ? 'Request an account' : mode === 'reset' ? 'Reset your password' : 'Sign in'}
      subtitle={
        mode === 'register'
          ? 'An administrator will review it and grant access.'
          : mode === 'reset'
            ? 'We will email you a link to choose a new one.'
            : 'Sign in to the company data and reporting workspace.'
      }
    >
      {error && (
        <div className="mb-4">
          <Alert variant="error">{error}</Alert>
        </div>
      )}
      {successMessage && (
        <div className="mb-4">
          <Alert variant="success">{successMessage}</Alert>
        </div>
      )}

      {mode === 'signin' && (
        <>
          <form onSubmit={handleSubmit} className="space-y-4" autoComplete="off">
            <Field label="Username">
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" />
                <Input
                  autoFocus
                  className="pl-9"
                  autoComplete="username"
                  name="orion-login-username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Username"
                />
              </div>
            </Field>

            <Field label="Password">
              <PasswordInput
                leading={<Lock className="h-4 w-4" />}
                className="pl-9"
                autoComplete="current-password"
                name="orion-login-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Password"
              />
            </Field>

            <Button type="submit" size="lg" loading={submitting} className="mt-2 w-full">
              Sign in
            </Button>
          </form>

          <div className="mt-4 flex flex-col items-center gap-2 text-sm">
            <button
              type="button"
              onClick={() => switchMode('register')}
              className="font-medium text-accent hover:underline"
            >
              Create account
            </button>
            <button
              type="button"
              onClick={() => switchMode('reset')}
              className="font-medium text-accent hover:underline"
            >
              Forgot password?
            </button>
            <Link to="/" className="text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]">
              Back to home
            </Link>
          </div>
        </>
      )}

      {mode === 'reset' && (
        <form onSubmit={handleReset} className="space-y-4" autoComplete="off">
          <p className="text-sm text-[color:var(--color-text-muted)]">
            Enter your username and the email on your account. If they match, we will send a reset link. If no
            email is on file, ask an administrator to reset your password.
          </p>
          <Field label="Username">
            <Input
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Username"
            />
          </Field>
          <Field label="Email on account">
            <Input
              type="email"
              autoComplete="email"
              value={resetEmail}
              onChange={(e) => setResetEmail(e.target.value)}
              placeholder="you@company.com"
            />
          </Field>
          <div className="flex gap-2">
            <Button type="button" variant="secondary" className="flex-1" onClick={() => switchMode('signin')}>
              Cancel
            </Button>
            <Button type="submit" loading={submitting} className="flex-1">
              Send reset link
            </Button>
          </div>
        </form>
      )}

      {mode === 'register' && (
        <form onSubmit={handleRegister} className="space-y-3" autoComplete="off">
          <p className="text-sm text-[color:var(--color-text-muted)]">
            Fill in your details. You will not be able to sign in until an administrator approves the request
            and chooses your access.
          </p>
          <Field label="Display name" required>
            <Input
              value={registerForm.display_name}
              onChange={(e) => setRegisterForm({ ...registerForm, display_name: e.target.value })}
              placeholder="Jane Doe"
              autoComplete="name"
            />
          </Field>
          <Field label="Username" required>
            <div className="relative">
              <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" />
              <Input
                className="pl-9"
                value={registerForm.username}
                onChange={(e) => setRegisterForm({ ...registerForm, username: e.target.value })}
                placeholder="jane.doe"
                autoComplete="off"
                name="orion-register-username"
              />
            </div>
          </Field>
          <Field label="Email" required>
            <div className="relative">
              <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" />
              <Input
                className="pl-9"
                type="email"
                value={registerForm.email}
                onChange={(e) => setRegisterForm({ ...registerForm, email: e.target.value })}
                placeholder="you@company.com"
                autoComplete="email"
              />
            </div>
          </Field>
          <Field label="Phone">
            <div className="relative">
              <Phone className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" />
              <Input
                className="pl-9"
                value={registerForm.phone}
                onChange={(e) => setRegisterForm({ ...registerForm, phone: e.target.value })}
                placeholder="Optional"
                autoComplete="tel"
              />
            </div>
          </Field>
          <Field label="Password" required>
            <PasswordInput
              value={registerForm.password}
              onChange={(e) => setRegisterForm({ ...registerForm, password: e.target.value })}
              placeholder="Min. 8 characters"
              autoComplete="new-password"
            />
          </Field>
          <Field label="Confirm password" required>
            <PasswordInput
              value={registerForm.confirm}
              onChange={(e) => setRegisterForm({ ...registerForm, confirm: e.target.value })}
              placeholder="Repeat password"
              autoComplete="new-password"
            />
          </Field>
          <PasswordStrength password={registerForm.password} confirm={registerForm.confirm} />
          <div className="flex gap-2 pt-1">
            <Button type="button" variant="secondary" className="flex-1" onClick={() => switchMode('signin')}>
              Cancel
            </Button>
            <Button type="submit" loading={submitting} className="flex-1">
              Submit request
            </Button>
          </div>
        </form>
      )}
    </AuthFrame>
  )
}
