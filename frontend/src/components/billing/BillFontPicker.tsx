import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { BASE_SIZE, FONTS, FONT_SIZES } from '../../billing/billFonts'
import type { BillFontOptions } from '../../types'
import { Field, Select } from '../ui/Field'

/** What the server can draw in the PDF, fetched once. Until it arrives (or if it fails) every typeface and size is offered. */
let cached: BillFontOptions | null = null

export function useBillFontOptions(): BillFontOptions | null {
  const [options, setOptions] = useState<BillFontOptions | null>(cached)
  useEffect(() => {
    if (cached) return
    let live = true
    api
      .billingFonts()
      .then((found) => {
        cached = found
        if (live) setOptions(found)
      })
      .catch(() => undefined) // the fixed list below is still right; the PDF falls back to Arial for a face the server lacks
    return () => {
      live = false
    }
  }, [])
  return options
}

const labelOf = (key: string) => FONTS.find((f) => f.key === key)?.label ?? key

/**
 * A typeface and a size for a bill. An empty value means "use the company's setting" (`company`), so a bill follows
 * the company until someone picks something for it.
 */
export function BillFontPicker({
  family,
  size,
  company,
  onChange,
  disabled,
}: {
  family: string
  size: string
  company: { family: string; size: number }
  onChange: (next: { family: string; size: string }) => void
  disabled?: boolean
}) {
  const options = useBillFontOptions()
  const families = options ? options.families.map((f) => ({ key: f.key, label: f.label })) : FONTS.map((f) => ({ key: f.key, label: f.label }))
  const sizes = options?.sizes ?? [...FONT_SIZES]
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <Field label="Typeface">
        <Select value={family} disabled={disabled} onChange={(event) => onChange({ family: event.target.value, size })}>
          <option value="">Company setting ({labelOf(company.family)})</option>
          {families.map((f) => (
            <option key={f.key} value={f.key}>
              {f.label}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Text size">
        <Select value={size} disabled={disabled} onChange={(event) => onChange({ family, size: event.target.value })}>
          <option value="">Company setting ({company.size} pt)</option>
          {sizes.map((value) => (
            <option key={value} value={String(value)}>
              {value} pt{value === BASE_SIZE ? ' (usual)' : ''}
            </option>
          ))}
        </Select>
      </Field>
    </div>
  )
}
