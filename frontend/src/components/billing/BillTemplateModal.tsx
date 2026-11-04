import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { BillProfile } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Field, Input, Select, Textarea } from '../ui/Field'
import { BASE_SIZE, DEFAULT_FONT, FONTS, FONT_SIZES } from '../../billing/billFonts'
import { useBillFontOptions } from './BillFontPicker'
import { Modal } from '../ui/Modal'

const TEXT_FIELDS: { key: keyof BillProfile; label: string; wide?: boolean }[] = [
  { key: 'company_name', label: 'Company name', wide: true },
  { key: 'address', label: 'Address', wide: true },
  { key: 'phone', label: 'Contact numbers', wide: true },
  { key: 'gstin', label: 'GSTIN' },
  { key: 'pan', label: 'PAN' },
  { key: 'pf_no', label: 'PF number' },
  { key: 'esi_no', label: 'ESI number' },
  { key: 'reg_no', label: 'Registration number' },
  { key: 'bank_name', label: 'Bank' },
  { key: 'bank_ifsc', label: 'IFSC' },
  { key: 'bank_account', label: 'Account number' },
  { key: 'signatory', label: 'Signed for' },
  { key: 'signatory_title', label: 'Signatory title' },
  { key: 'default_service_description', label: 'Usual service description', wide: true },
]

/** The part of every bill that does not change: letterhead, registrations, bank, terms, signature. */
export function BillTemplateModal({
  open,
  canEdit,
  onClose,
  onSaved,
}: {
  open: boolean
  canEdit: boolean
  onClose: () => void
  onSaved: (profile: BillProfile) => void
}) {
  const [profile, setProfile] = useState<BillProfile | null>(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const fontOptions = useBillFontOptions()
  const families = fontOptions ? fontOptions.families : FONTS
  const sizes = fontOptions?.sizes ?? [...FONT_SIZES]

  useEffect(() => {
    if (!open) return
    setError('')
    api
      .billingProfile()
      .then(setProfile)
      .catch((e: Error) => setError(e.message))
  }, [open])

  const set = (key: keyof BillProfile, value: string) =>
    setProfile((current) => (current ? { ...current, [key]: value } : current))

  const save = async () => {
    if (!profile) return
    setSaving(true)
    setError('')
    try {
      const saved = await api.saveBillingProfile(profile)
      onSaved(saved)
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      title="Bill template"
      size="xl"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {canEdit ? 'Cancel' : 'Close'}
          </Button>
          {canEdit && (
            <Button onClick={save} loading={saving} disabled={!profile}>
              Save template
            </Button>
          )}
        </>
      }
    >
      <p className="mb-4 text-sm text-[color:var(--color-text-muted)]">
        This is the common top and bottom of every bill. Changing it affects new bills only: each issued bill keeps the
        letterhead it was issued with.
      </p>
      {error && <Alert variant="error">{error}</Alert>}
      {profile && (
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          {TEXT_FIELDS.map((field) => (
            <Field key={field.key} label={field.label} className={field.wide ? 'sm:col-span-2' : ''}>
              <Input
                value={String(profile[field.key] ?? '')}
                disabled={!canEdit}
                onChange={(event) => set(field.key, event.target.value)}
              />
            </Field>
          ))}
          <Field label="Typeface of the bills" hint="A bill can be given a typeface of its own when it is made or opened.">
            <Select
              value={profile.font_family ?? DEFAULT_FONT.family}
              disabled={!canEdit}
              onChange={(event) => setProfile({ ...profile, font_family: event.target.value })}
            >
              {families.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Text size of the bills" hint="Larger sizes scale the whole bill. Unlike the details above, this applies to issued bills too, unless a bill has its own.">
            <Select
              value={String(profile.font_size ?? DEFAULT_FONT.size)}
              disabled={!canEdit}
              onChange={(event) => setProfile({ ...profile, font_size: Number(event.target.value) })}
            >
              {sizes.map((value) => (
                <option key={value} value={String(value)}>
                  {value} pt{value === BASE_SIZE ? ' (usual)' : ''}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Terms (one per line)" className="sm:col-span-2">
            <Textarea
              rows={4}
              value={profile.terms.join('\n')}
              disabled={!canEdit}
              onChange={(event) => setProfile({ ...profile, terms: event.target.value.split('\n') })}
            />
          </Field>
        </div>
      )}
    </Modal>
  )
}
