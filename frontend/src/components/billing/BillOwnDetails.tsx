import type { BillProfile, BillProfileEdits } from '../../types'
import { Field, Input, Textarea } from '../ui/Field'

/**
 * The details of the template that one bill can print differently (mirrors PROFILE_BILL_KEYS in backend/app/billing.py).
 * The usual service description is not here: it only fills in the form.
 */
const FIELDS: { key: keyof BillProfileEdits; label: string; wide?: boolean }[] = [
  { key: 'bank_name', label: 'Bank' },
  { key: 'bank_ifsc', label: 'IFSC' },
  { key: 'bank_account', label: 'Account number' },
  { key: 'signatory', label: 'Signed for' },
  { key: 'signatory_title', label: 'Signatory title' },
  { key: 'company_name', label: 'Company name', wide: true },
  { key: 'address', label: 'Address', wide: true },
  { key: 'phone', label: 'Contact numbers', wide: true },
  { key: 'gstin', label: 'GSTIN' },
  { key: 'pan', label: 'PAN' },
  { key: 'pf_no', label: 'PF number' },
  { key: 'esi_no', label: 'ESI number' },
  { key: 'reg_no', label: 'Registration number' },
]

const same = (a: string | string[] | undefined, b: string | string[] | undefined) =>
  Array.isArray(a) || Array.isArray(b) ? JSON.stringify(a ?? []) === JSON.stringify(b ?? []) : (a ?? '') === (b ?? '')

/**
 * "Company, bank and terms on this bill": the template's details as this bill prints them, each editable for this bill only.
 * `base` is what the bill would print without edits (the template for a new bill, the bill's own copy for an issued one),
 * `own` the edits made here, and `template` today's template, which a detail can be put back to.
 */
export function BillOwnDetails({
  base,
  template,
  own,
  onChange,
}: {
  base: BillProfile
  template: BillProfile | null
  own: BillProfileEdits
  onChange: (next: BillProfileEdits) => void
}) {
  const shown = { ...base, ...own }
  const set = (key: keyof BillProfileEdits, value: string | string[]) => {
    const next = { ...own, [key]: value }
    if (same(value, base[key])) delete next[key] // typed back to what it was: no longer an edit
    onChange(next)
  }
  const differing = FIELDS.map((f) => f.key).concat('terms').filter((key) => template && !same(shown[key], template[key])).length

  /** Under a detail that is not the template's: what the template has, and a way back to it. */
  const note = (key: keyof BillProfileEdits) =>
    template && !same(shown[key], template[key]) ? (
      <span className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-[color:var(--color-text-muted)]">
        Template: {Array.isArray(template[key]) ? (template[key] as string[]).join(' / ') || '(none)' : String(template[key] || '(none)')}
        <button type="button" className="underline hover:text-[color:var(--color-text)]" onClick={() => set(key, template[key] as string | string[])}>
          Use the template's
        </button>
      </span>
    ) : null

  return (
    <details className="rounded-xl border border-[color:var(--color-border)] bg-surface p-4" open={Object.keys(own).length > 0}>
      <summary className="cursor-pointer text-sm font-semibold text-[color:var(--color-text)]">
        Company, bank and terms on this bill
        <span className="ml-2 text-xs font-normal text-[color:var(--color-text-muted)]">
          {differing ? `${differing} different from the template` : 'As in the template'}
        </span>
      </summary>
      <p className="mt-2 text-xs text-[color:var(--color-text-muted)]">
        These come from the Bill template. Change one here and only this bill prints it (and the next bill for this case starts with it).
        The template itself, and other bills, stay as they are. To hide a part altogether, use "What shows on the bill".
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {FIELDS.map((field) => (
          <Field key={field.key} label={field.label} className={field.wide ? 'sm:col-span-2' : ''}>
            <div>
              <Input value={String(shown[field.key] ?? '')} maxLength={300} onChange={(event) => set(field.key, event.target.value)} />
              {note(field.key)}
            </div>
          </Field>
        ))}
        <Field label="Terms (one per line)" className="sm:col-span-2">
          <div>
            <Textarea rows={4} value={shown.terms.join('\n')} onChange={(event) => set('terms', event.target.value.split('\n'))} />
            {note('terms')}
          </div>
        </Field>
      </div>
    </details>
  )
}
