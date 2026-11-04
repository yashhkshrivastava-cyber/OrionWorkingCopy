import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { forwardRef, useId } from 'react'

const fieldClass =
  'w-full min-h-11 rounded-lg border border-[color:var(--color-border-strong)] bg-surface px-3 py-2 text-base text-[color:var(--color-text)] placeholder:text-[color:var(--color-text-faint)] transition-[border-color,box-shadow] duration-[var(--orion-dur-fast)] hover:border-[color:var(--color-text-faint)] focus:border-accent focus:ring-[3px] focus:ring-[color:var(--orion-ring)] disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-negative sm:min-h-0 sm:text-sm'

export function Field({
  label,
  required,
  hint,
  children,
  className = '',
}: {
  label?: string
  required?: boolean
  /** Helper text under the control. */
  hint?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`space-y-1.5 ${className}`}>
      {label && (
        <label className="t-label block text-[color:var(--color-text)]">
          {label}
          {required ? <span className="text-negative" aria-hidden="true"> *</span> : null}
          {required ? <span className="sr-only"> (required)</span> : null}
        </label>
      )}
      {children}
      {hint && <p className="t-caption">{hint}</p>}
    </div>
  )
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = '', ...props }, ref) {
    return <input ref={ref} className={`${fieldClass} ${className}`} {...props} />
  },
)

export function Select({ className = '', ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={`${fieldClass} cursor-pointer ${className}`} {...props} />
}

export function Textarea({ className = '', ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`${fieldClass} min-h-[88px] resize-y ${className}`} {...props} />
}

export function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <label className="group flex cursor-pointer items-center gap-2.5">
      <input
        type="checkbox"
        className="peer sr-only"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span
        aria-hidden="true"
        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors duration-[var(--orion-dur-fast)] peer-focus-visible:ring-[3px] peer-focus-visible:ring-[color:var(--orion-ring)] ${
          checked
            ? 'border-primary bg-primary text-on-primary'
            : 'border-[color:var(--color-border-strong)] bg-surface group-hover:border-[color:var(--color-accent)]'
        }`}
      >
        {checked && (
          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        )}
      </span>
      <span className="text-sm text-[color:var(--color-text-muted)] group-hover:text-[color:var(--color-text)]">
        {label}
      </span>
    </label>
  )
}

/** An on/off setting that takes effect at once. Announced to screen readers as a switch, with its label and hint. */
export function Switch({
  label,
  hint,
  checked,
  onChange,
  disabled,
}: {
  label: string
  hint?: string
  checked: boolean
  onChange: (value: boolean) => void
  disabled?: boolean
}) {
  const id = useId()
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <label htmlFor={id} className="t-label block cursor-pointer text-[color:var(--color-text)]">
          {label}
        </label>
        {hint && <p className="t-caption mt-0.5">{hint}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`interactive relative mt-0.5 inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-[var(--orion-dur-base)] disabled:cursor-not-allowed disabled:opacity-50 ${
          checked ? 'border-primary bg-primary' : 'border-[color:var(--color-border-strong)] bg-muted'
        }`}
      >
        <span
          aria-hidden="true"
          className={`absolute left-0.5 h-[18px] w-[18px] rounded-full shadow-card transition-transform duration-[var(--orion-dur-base)] ease-[var(--orion-ease)] ${
            checked ? 'translate-x-5 bg-on-primary' : 'translate-x-0 bg-[color:var(--color-text-faint)]'
          }`}
        />
      </button>
    </div>
  )
}
