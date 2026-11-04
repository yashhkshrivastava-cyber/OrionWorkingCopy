import { FormEvent, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Camera, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { User } from '../types'
import { useAuth } from '../context/AuthContext'
import { useDataRefresh } from '../context/DataRefreshContext'
import { useLumen } from '../lumen/useLumen'
import { AppearanceSettings } from '../components/appearance/AppearanceSettings'
import { AiSettings } from '../components/assistant/AiSettings'
import { Tabs } from '../components/ui/Tabs'
import { OPEN_WELCOME } from '../components/welcome/events'
import { UserAvatar } from '../components/UserAvatar'
import { SignedInDevices } from '../components/SignedInDevices'
import { PageHeader } from '../components/ui/PageHeader'
import { Card, CardHeader } from '../components/ui/Card'
import { Field, Input } from '../components/ui/Field'
import { Button } from '../components/ui/Button'
import { Alert } from '../components/ui/Alert'
import { useToast } from '../components/ui/Toast'

export function SettingsPage() {
  const { user, refresh, applyUser } = useAuth()
  const { generation } = useDataRefresh()
  const lumen = useLumen()
  const [params, setParams] = useSearchParams()
  const wanted = params.get('tab')
  const tab: 'profile' | 'appearance' | 'ai' = wanted === 'appearance' ? 'appearance' : wanted === 'ai' && user?.can_ai ? 'ai' : 'profile'
  const fileRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState(user?.display_name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [phone, setPhone] = useState(user?.phone ?? '')
  const [error, setError] = useState('')
  const toast = useToast()
  const [saving, setSaving] = useState(false)
  const [photoBusy, setPhotoBusy] = useState(false)

  useEffect(() => {
    void refresh()
  }, [refresh, generation])

  useEffect(() => {
    setName(user?.display_name ?? '')
    setEmail(user?.email ?? '')
    setPhone(user?.phone ?? '')
  }, [user?.display_name, user?.email, user?.phone])

  if (!user) return null

  const flash = (text: string) => toast.show(text)

  const saveContact = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setSaving(true)
    try {
      await api.updateProfile({ email: email.trim(), phone: phone.trim() })
      await refresh()
      flash('Contact details saved.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save contact details')
    } finally {
      setSaving(false)
    }
  }

  /** Name, email and phone together, for the single form of the Lumen profile. Only what changed is sent. */
  const saveDetails = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    const next = name.trim()
    if (!next) {
      setError('Enter a name.')
      return
    }
    setSaving(true)
    try {
      await api.updateProfile({
        ...(next !== user?.display_name ? { display_name: next } : {}),
        ...(email.trim() !== (user?.email || '') || phone.trim() !== (user?.phone || '') ? { email: email.trim(), phone: phone.trim() } : {}),
      })
      await refresh()
      flash('Your details are saved.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save your details')
    } finally {
      setSaving(false)
    }
  }

  const saveName = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    const next = name.trim()
    if (!next) {
      setError('Enter a name.')
      return
    }
    setSaving(true)
    try {
      await api.updateProfile({ display_name: next })
      await refresh()
      flash('Name saved.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save name')
    } finally {
      setSaving(false)
    }
  }

  const onPhoto = async (file?: File) => {
    if (!file) return
    setError('')
    setPhotoBusy(true)
    try {
      const next = (await api.uploadAvatar(file)) as User
      applyUser(next)
      flash('Photo updated.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not upload photo')
    } finally {
      setPhotoBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const removePhoto = async () => {
    setError('')
    setPhotoBusy(true)
    try {
      const next = (await api.removeAvatar()) as User
      applyUser(next)
      flash('Photo removed.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove photo')
    } finally {
      setPhotoBusy(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="Your profile, how the workspace looks, and your AI Copilot."
      />

      <div className="mb-5">
        <Tabs<'profile' | 'appearance' | 'ai'>
          label="Settings sections"
          tabs={[
            { id: 'profile', label: 'Profile' },
            { id: 'appearance', label: 'Appearance' },
            ...(user.can_ai ? [{ id: 'ai' as const, label: 'AI Copilot' }] : []),
          ]}
          active={tab}
          onChange={(next) => setParams(next === 'profile' ? {} : { tab: next }, { replace: true })}
        />
      </div>

      {error && (
        <div className="mb-4">
          <Alert variant="error" onDismiss={() => setError('')}>
            {error}
          </Alert>
        </div>
      )}

      {tab === 'appearance' ? (
        <AppearanceSettings />
      ) : tab === 'ai' ? (
        <AiSettings />
      ) : lumen ? (
        <div className="space-y-5">
          <section
            aria-label="Your profile"
            className="panel relative overflow-hidden !p-0 text-[color:var(--orion-on-primary)]"
            style={{ backgroundImage: 'var(--orion-highlight-fill)' }}
          >
            <span className="lumen-orb pointer-events-none absolute -right-10 -top-14 h-56 w-56 rounded-full bg-white/20 blur-2xl" aria-hidden="true" />
            <div className="relative flex flex-wrap items-center gap-6 p-6 sm:p-8">
              <span className="relative">
                <UserAvatar user={user} size="lg" className="ring-4 ring-white/40" />
                <button
                  type="button"
                  onClick={() => fileRef.current?.click()}
                  disabled={photoBusy}
                  aria-label={user.has_avatar ? 'Change your photo' : 'Add a photo'}
                  className="interactive absolute -bottom-1 -right-1 grid h-9 w-9 place-items-center rounded-full bg-surface text-[color:var(--color-text)] shadow-card disabled:opacity-60"
                >
                  <Camera className="h-4 w-4" aria-hidden="true" />
                </button>
                <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(event) => onPhoto(event.target.files?.[0])} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-bold uppercase tracking-[0.12em] opacity-90">Your profile</p>
                <h2 className="font-display mt-1 truncate text-3xl font-semibold leading-tight sm:text-4xl">{user.display_name}</h2>
                <p className="mt-1 text-sm opacity-90">
                  @{user.username} · <span className="capitalize">{user.role}</span>
                </p>
                {user.has_avatar && (
                  <button type="button" onClick={removePhoto} disabled={photoBusy} className="interactive mt-3 inline-flex items-center gap-1.5 rounded-full bg-white/20 px-3.5 py-1.5 text-sm font-semibold hover:bg-white/30 disabled:opacity-60">
                    <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Remove photo
                  </button>
                )}
              </div>
            </div>
          </section>

          <div className="grid items-start gap-5 lg:grid-cols-2">
            <section className="panel !p-6" aria-label="Your details">
              <h3 className="font-display text-lg font-semibold">Your details</h3>
              <p className="t-small mb-4 mt-0.5 text-[color:var(--color-text-muted)]">Your name is what other people see. Your email and phone are used to recover your password from the sign-in page.</p>
              <form onSubmit={saveDetails} className="space-y-4">
                <Field label="Display name">
                  <Input value={name} onChange={(event) => setName(event.target.value)} maxLength={80} />
                </Field>
                <Field label="Username">
                  <Input value={user.username} disabled />
                </Field>
                <Field label="Email">
                  <Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" />
                </Field>
                <Field label="Phone">
                  <Input type="tel" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="+91 9876543210" />
                </Field>
                <Button
                  type="submit"
                  loading={saving}
                  disabled={name.trim() === user.display_name && email.trim() === (user.email || '') && phone.trim() === (user.phone || '')}
                >
                  Save details
                </Button>
              </form>
            </section>
            <div className="space-y-5">
              <SignedInDevices />
              <section className="panel !p-6" aria-label="The welcome tour">
                <h3 className="font-display text-lg font-semibold">New here, or forgotten something?</h3>
                <p className="t-small mb-3 mt-0.5 text-[color:var(--color-text-muted)]">The welcome shows how Orion can look and what your account opens.</p>
                <Button type="button" variant="secondary" onClick={() => window.dispatchEvent(new Event(OPEN_WELCOME))}>
                  Show the welcome again
                </Button>
              </section>
            </div>
          </div>
        </div>
      ) : (
      <div className="grid max-w-3xl gap-5">
          <Card accent="blue">
            <CardHeader title="Profile photo" subtitle="Shown in the header and on your account" />
            <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center">
              <UserAvatar user={user} size="lg" />
              <div className="flex flex-wrap gap-2">
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(event) => onPhoto(event.target.files?.[0])}
                />
                <Button
                  type="button"
                  variant="secondary"
                  loading={photoBusy}
                  onClick={() => fileRef.current?.click()}
                >
                  <Camera className="h-4 w-4" />
                  {user.has_avatar ? 'Change photo' : 'Add photo'}
                </Button>
                {user.has_avatar && (
                  <Button type="button" variant="ghost" disabled={photoBusy} onClick={removePhoto}>
                    <Trash2 className="h-4 w-4" />
                    Remove
                  </Button>
                )}
                <p className="w-full text-xs text-[color:var(--color-text-faint)]">
                  Any photo from your phone or computer. We resize it automatically.
                </p>
              </div>
            </div>
          </Card>

          <Card accent="teal">
            <CardHeader title="Name" subtitle="This is what other people see. Your username stays the same." />
            <form onSubmit={saveName} className="space-y-4">
              <Field label="Display name">
                <Input value={name} onChange={(event) => setName(event.target.value)} maxLength={80} />
              </Field>
              <Field label="Username">
                <Input value={user.username} disabled />
              </Field>
              <Button type="submit" loading={saving} disabled={name.trim() === user.display_name}>
                Save name
              </Button>
            </form>
          </Card>

          <Card accent="amber">
            <CardHeader title="Contact" subtitle="Used for password recovery on the sign-in page" />
            <form onSubmit={saveContact} className="space-y-4">
              <Field label="Email">
                <Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@company.com" />
              </Field>
              <Field label="Phone">
                <Input type="tel" value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="+91 9876543210" />
              </Field>
              <Button
                type="submit"
                loading={saving}
                disabled={email.trim() === (user.email || '') && phone.trim() === (user.phone || '')}
              >
                Save contact
              </Button>
            </form>
          </Card>

          <SignedInDevices />

          <Card accent="violet">
            <CardHeader title="Welcome tour" subtitle="How Orion can look and what your account opens" />
            <Button type="button" variant="secondary" onClick={() => window.dispatchEvent(new Event(OPEN_WELCOME))}>
              Show the welcome again
            </Button>
          </Card>
      </div>
      )}
    </div>
  )
}
