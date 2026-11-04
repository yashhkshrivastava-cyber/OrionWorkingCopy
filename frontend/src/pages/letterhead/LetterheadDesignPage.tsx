import { useEffect, useRef, useState } from 'react'
import { ImageUp, RotateCcw } from 'lucide-react'
import { api } from '../../api/client'
import { formatDay } from '../../components/billing/BillDocument'
import { LetterheadSheet, setLetterheadDesign, useLetterheadDesign } from '../../components/letterhead/LetterheadSheet'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Field'
import { useAuth } from '../../context/AuthContext'
import type { LetterheadDesign, LetterheadSettingKey, LetterheadSettings } from '../../types'

type Part = 'header' | 'footer'

const SPACING: { key: LetterheadSettingKey; label: string; hint: string }[] = [
  { key: 'header_top_mm', label: 'Above the header', hint: 'From the top edge of the paper to the header.' },
  { key: 'footer_bottom_mm', label: 'Below the footer', hint: 'From the footer to the bottom edge of the paper.' },
  { key: 'side_mm', label: 'Beside the header and footer', hint: 'Left and right of both. 0 runs them edge to edge.' },
  { key: 'body_gap_top_mm', label: 'Header to text', hint: 'Clear space under the header before the text starts.' },
  { key: 'body_gap_bottom_mm', label: 'Text to footer', hint: 'Clear space kept above the footer.' },
  { key: 'body_left_mm', label: 'Left margin of the text', hint: 'For letters. Bills keep their own margins.' },
  { key: 'body_right_mm', label: 'Right margin of the text', hint: 'For letters. Bills keep their own margins.' },
]

function StripCard({
  part,
  design,
  canEdit,
  onChanged,
  onError,
}: {
  part: Part
  design: LetterheadDesign
  canEdit: boolean
  onChanged: (design: LetterheadDesign, message: string) => void
  onError: (message: string) => void
}) {
  const picker = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const strip = design[part]
  const name = part === 'header' ? 'Header' : 'Footer'
  const height = part === 'header' ? design.layout.header_height_mm : design.layout.footer_height_mm

  const upload = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    try {
      onChanged(await api.uploadLetterheadImage(part, file), `The ${part} is replaced. It is used from now on, everywhere.`)
    } catch (e) {
      onError((e as Error).message)
    } finally {
      setBusy(false)
      if (picker.current) picker.current.value = ''
    }
  }

  const reset = async () => {
    setBusy(true)
    try {
      onChanged(await api.resetLetterheadImage(part), `The ${part} is back to the original.`)
    } catch (e) {
      onError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="space-y-3 rounded-xl border border-[color:var(--color-border)] bg-surface p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-[color:var(--color-text)]">{name}</h3>
        <span className="text-xs text-[color:var(--color-text-muted)]">
          {strip.custom ? 'Replaced' : 'Original'} · {strip.width} × {strip.height} px · prints {height.toFixed(0)} mm tall
        </span>
      </div>
      <div className="overflow-hidden rounded-lg border border-[color:var(--color-border)] bg-white">
        <img src={strip.url} alt={`The ${part} as it prints`} className="block w-full" />
      </div>
      {canEdit && (
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={picker}
            type="file"
            accept="image/jpeg,image/png,.jpg,.jpeg,.png"
            className="sr-only"
            onChange={(event) => upload(event.target.files?.[0])}
          />
          <Button variant="secondary" size="sm" loading={busy} onClick={() => picker.current?.click()}>
            <ImageUp className="h-4 w-4" /> Replace the {part}
          </Button>
          {strip.custom && (
            <Button variant="ghost" size="sm" disabled={busy} onClick={reset}>
              <RotateCcw className="h-4 w-4" /> Use the original
            </Button>
          )}
        </div>
      )}
    </section>
  )
}

/**
 * The letterhead itself: its two image strips and where they sit on the page. Everyone with access can see
 * it; only an admin can change it, because a change shows on every letter and bill printed afterwards.
 */
export function LetterheadDesignPage() {
  const { user } = useAuth()
  const canEdit = user?.role === 'admin'
  const { design, error: loadError } = useLetterheadDesign()
  const [spacing, setSpacing] = useState<Record<LetterheadSettingKey, string> | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)

  const fill = (from: LetterheadSettings) =>
    setSpacing(Object.fromEntries(SPACING.map(({ key }) => [key, String(from[key])])) as Record<LetterheadSettingKey, string>)

  // The fields follow the saved letterhead until someone types in them.
  useEffect(() => {
    if (design && spacing === null) fill(design.settings)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [design])

  const changed = (next: LetterheadDesign, message: string) => {
    setLetterheadDesign(next)
    fill(next.settings)
    setError('')
    setNotice(message)
  }

  const numbers = (): LetterheadSettings | null => {
    if (!design || !spacing) return null
    const out = {} as LetterheadSettings
    for (const { key, label } of SPACING) {
      const value = Number(spacing[key])
      const { min, max } = design.limits[key]
      if (spacing[key].trim() === '' || !Number.isFinite(value) || value < min || value > max) {
        setError(`"${label}" must be a number from ${min} to ${max} mm.`)
        return null
      }
      out[key] = value
    }
    return out
  }

  const save = async (values: LetterheadSettings | null) => {
    if (!values) return
    setSaving(true)
    setNotice('')
    try {
      changed(await api.saveLetterheadSettings(values), 'The spacing is saved. The page on the right shows it.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const defaults = () =>
    design && save(Object.fromEntries(SPACING.map(({ key }) => [key, design.limits[key].default])) as LetterheadSettings)

  const dirty = Boolean(design && spacing && SPACING.some(({ key }) => Number(spacing[key]) !== design.settings[key]))

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-[color:var(--color-text)]">Header and footer</h2>
        <p className="text-sm text-[color:var(--color-text-muted)]">
          The letterhead is two pictures: a header across the top of the page and a footer across the bottom.{' '}
          {canEdit
            ? 'Replace either with a new picture, or move them. A change applies to everything printed on the letterhead from then on.'
            : 'An admin can replace them or move them.'}
        </p>
      </div>

      {(error || loadError) && <Alert variant="error">{error || loadError}</Alert>}
      {notice && (
        <Alert variant="success" onDismiss={() => setNotice('')}>
          {notice}
        </Alert>
      )}

      {!design ? (
        <div className="shimmer h-64 rounded-xl bg-muted" aria-busy="true" />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
          <div className="space-y-4">
            <StripCard part="header" design={design} canEdit={canEdit} onChanged={changed} onError={setError} />
            <StripCard part="footer" design={design} canEdit={canEdit} onChanged={changed} onError={setError} />
            {canEdit && (
              <p className="text-xs text-[color:var(--color-text-muted)]">
                A replacement is a JPG or PNG, a wide strip at least 600 pixels across (1,600 or more prints sharply),
                up to 8 MB. The words inside a strip are part of the picture: to change the address or a number, make
                the new strip in the program the letterhead was designed in and upload it here.
              </p>
            )}

            <section className="space-y-3 rounded-xl border border-[color:var(--color-border)] bg-surface p-4">
              <h3 className="text-sm font-semibold text-[color:var(--color-text)]">Spacing, in millimetres</h3>
              {spacing &&
                SPACING.map(({ key, label, hint }) => (
                  <label key={key} className="grid grid-cols-[minmax(0,1fr)_5.5rem] items-center gap-3">
                    <span>
                      <span className="block text-[13px] font-medium text-[color:var(--color-text)]">{label}</span>
                      <span className="block text-xs text-[color:var(--color-text-muted)]">{hint}</span>
                    </span>
                    <Input
                      type="number"
                      step="0.5"
                      min={design.limits[key].min}
                      max={design.limits[key].max}
                      value={spacing[key]}
                      disabled={!canEdit}
                      onChange={(event) => setSpacing({ ...spacing, [key]: event.target.value })}
                    />
                  </label>
                ))}
              {canEdit && (
                <div className="flex flex-wrap gap-2 pt-1">
                  <Button onClick={() => save(numbers())} loading={saving} disabled={!dirty}>
                    Save spacing
                  </Button>
                  <Button variant="ghost" onClick={defaults} disabled={saving}>
                    Back to the standard spacing
                  </Button>
                </div>
              )}
            </section>

            {design.updated_timestamp && (
              <p className="text-xs text-[color:var(--color-text-muted)]">
                Last changed {formatDay(design.updated_timestamp)}
                {design.updated_by_name ? ` by ${design.updated_by_name}` : ''}.
              </p>
            )}
          </div>

          <section className="min-w-0 space-y-2">
            <p className="text-xs font-medium text-[color:var(--color-text-muted)]">
              An A4 page as it prints now. The grey block is where a letter's text goes.
            </p>
            <div className="overflow-x-auto rounded-xl bg-muted p-3 sm:p-5">
              <LetterheadSheet design={design}>
                <div
                  className="rounded border border-dashed border-slate-300 bg-slate-100/70"
                  style={{ height: `${design.page.height_mm - design.layout.top_space_mm - design.layout.bottom_space_mm}mm` }}
                />
              </LetterheadSheet>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
