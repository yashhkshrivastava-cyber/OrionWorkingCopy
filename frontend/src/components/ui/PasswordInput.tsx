import { useState, type InputHTMLAttributes, type KeyboardEvent, type ReactNode } from 'react'
import { Eye, EyeOff, TriangleAlert } from 'lucide-react'
import { Input } from './Field'

/** A password box with a show/hide button, and a quiet warning while Caps Lock is on (the commonest reason a right password is refused). */
export function PasswordInput({ className = '', leading, onKeyDown, onKeyUp, onBlur, ...props }: InputHTMLAttributes<HTMLInputElement> & { leading?: ReactNode }) {
  const [visible, setVisible] = useState(false)
  const [caps, setCaps] = useState(false)
  const watch = (event: KeyboardEvent<HTMLInputElement>) => setCaps(event.getModifierState('CapsLock'))

  return (
    <div>
      <div className="relative">
        {leading && <span className="pointer-events-none absolute left-3 top-1/2 z-10 -translate-y-1/2 text-[color:var(--color-text-faint)]">{leading}</span>}
        <Input
          {...props}
          type={visible ? 'text' : 'password'}
          className={`pr-10 ${className}`.trim()}
          onKeyDown={(event) => {
            watch(event)
            onKeyDown?.(event)
          }}
          onKeyUp={(event) => {
            watch(event)
            onKeyUp?.(event)
          }}
          onBlur={(event) => {
            setCaps(false)
            onBlur?.(event)
          }}
        />
        <button
          type="button"
          tabIndex={-1}
          aria-label={visible ? 'Hide password' : 'Show password'}
          onClick={() => setVisible((v) => !v)}
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]"
        >
          {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
      {caps && (
        <p role="status" className="t-caption mt-1.5 flex items-center gap-1.5 font-medium text-warning">
          <TriangleAlert className="h-3.5 w-3.5" aria-hidden="true" /> Caps Lock is on
        </p>
      )}
    </div>
  )
}
