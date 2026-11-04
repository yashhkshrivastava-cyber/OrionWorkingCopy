import { useId, type ReactNode } from 'react'
import { Checkbox, Input, Select } from '../../components/ui/Field'
import { PasswordInput } from '../../components/ui/PasswordInput'
import { Segmented } from '../../components/ui/Segmented'
import type { FieldSpec, Values } from './tools'

/** A control with its words tied to it, so a screen reader says what each box is for (the shared Field does not). */
function Labelled({ id, label, hint, required, children }: { id: string; label: string; hint?: string; required?: boolean; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="t-label block text-[color:var(--color-text)]">
        {label}
        {required && (
          <>
            <span className="text-negative" aria-hidden="true">
              {' '}
              *
            </span>
            <span className="sr-only"> (required)</span>
          </>
        )}
      </label>
      {children}
      {hint && (
        <p id={`${id}-hint`} className="t-caption">
          {hint}
        </p>
      )}
    </div>
  )
}

function OneField({ spec, value, onChange, pageCount }: { spec: FieldSpec; value: string | boolean; onChange: (next: string | boolean) => void; pageCount?: number | null }) {
  const id = useId()
  const hinted = spec.hint ? { 'aria-describedby': `${id}-hint` } : {}

  switch (spec.kind) {
    case 'check':
      return (
        <div className="space-y-1">
          <Checkbox label={spec.label} checked={Boolean(value)} onChange={onChange} />
          {spec.hint && <p className="t-caption pl-6">{spec.hint}</p>}
        </div>
      )
    case 'choice':
      return (
        <div className="space-y-1.5">
          {spec.options.length <= 4 ? (
            <>
              <p className="t-label text-[color:var(--color-text)]">{spec.label}</p>
              <Segmented label={spec.label} value={String(value)} options={spec.options} onChange={onChange} />
              {spec.hint && <p className="t-caption">{spec.hint}</p>}
            </>
          ) : (
            <Labelled id={id} label={spec.label} hint={spec.hint}>
              <Select id={id} value={String(value)} onChange={(event) => onChange(event.target.value)} {...hinted}>
                {spec.options.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </Labelled>
          )}
        </div>
      )
    case 'number':
      return (
        <Labelled id={id} label={spec.label} hint={spec.hint}>
          <Input
            id={id}
            type="number"
            inputMode="numeric"
            min={spec.min}
            max={spec.max}
            value={String(value)}
            onChange={(event) => onChange(event.target.value)}
            {...hinted}
          />
        </Labelled>
      )
    case 'password':
      return (
        <Labelled id={id} label={spec.label} hint={spec.hint} required={spec.required}>
          <PasswordInput id={id} value={String(value)} autoComplete="new-password" maxLength={128} onChange={(event) => onChange(event.target.value)} {...hinted} />
        </Labelled>
      )
    case 'pages':
      return (
        <Labelled id={id} label={spec.label} required={spec.required} hint={`${spec.hint ?? ''}${pageCount ? ` This PDF has ${pageCount} ${pageCount === 1 ? 'page' : 'pages'}.` : ''}`.trim()}>
          <Input id={id} value={String(value)} placeholder={spec.placeholder} spellCheck={false} autoComplete="off" maxLength={300} onChange={(event) => onChange(event.target.value)} {...hinted} />
        </Labelled>
      )
    default:
      return (
        <Labelled id={id} label={spec.label} required={spec.required} hint={spec.hint}>
          <Input id={id} value={String(value)} placeholder={spec.placeholder} maxLength={spec.max ?? 200} autoComplete="off" onChange={(event) => onChange(event.target.value)} {...hinted} />
        </Labelled>
      )
  }
}

/** The options of one tool, drawn from its definition. A field whose `showIf` is false for the values so far is left out. */
export function OptionFields({
  fields,
  values,
  onChange,
  pageCount,
}: {
  fields: FieldSpec[]
  values: Values
  onChange: (key: string, next: string | boolean) => void
  pageCount?: number | null
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {fields
        .filter((spec) => !spec.showIf || spec.showIf(values))
        .map((spec) => (
          <div key={spec.key} className={spec.kind === 'check' || spec.kind === 'pages' || (spec.kind === 'choice' && spec.options.length > 3) ? 'sm:col-span-2' : ''}>
            <OneField spec={spec} value={values[spec.key] ?? ''} onChange={(next) => onChange(spec.key, next)} pageCount={spec.kind === 'pages' ? pageCount : undefined} />
          </div>
        ))}
    </div>
  )
}
