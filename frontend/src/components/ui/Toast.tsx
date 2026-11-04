import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { CircleAlert, CircleCheck, Info, X } from 'lucide-react'
import { usePresence } from '../../hooks/usePresence'

type Tone = 'success' | 'error' | 'info'

type ToastItem = { id: number; tone: Tone; message: string; detail?: string }

type ToastApi = {
  /** A short message that fades away by itself. Errors stay a little longer. */
  show: (message: string, options?: { tone?: Tone; detail?: string }) => void
}

const ToastContext = createContext<ToastApi | null>(null)

const ICON = { success: CircleCheck, error: CircleAlert, info: Info }
const TONE = {
  success: '[&>svg]:text-positive',
  error: '[&>svg]:text-negative',
  info: '[&>svg]:text-accent',
}

function Toast({ item, onDone }: { item: ToastItem; onDone: (id: number) => void }) {
  const [open, setOpen] = useState(true)
  const { present, leaving } = usePresence(open)
  const Icon = ICON[item.tone]

  const dismiss = () => {
    setOpen(false)
    window.setTimeout(() => onDone(item.id), 220)
  }

  // Dismissed on its own after a while; an error stays a little longer. The message is short, so it is not paused on hover.
  useEffect(() => {
    const timer = window.setTimeout(dismiss, item.tone === 'error' ? 7000 : 4200)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!present) return null
  return (
    <div
      role={item.tone === 'error' ? 'alert' : 'status'}
      className={`${leaving ? 'pop-out' : 'toast-in'} overlay pointer-events-auto flex items-start gap-3 rounded-xl border border-[color:var(--color-border)] px-4 py-3 text-sm ${TONE[item.tone]}`}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-[color:var(--color-text)]">{item.message}</p>
        {item.detail && <p className="t-caption mt-0.5 break-words">{item.detail}</p>}
      </div>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        className="interactive -mr-1 shrink-0 rounded p-0.5 text-[color:var(--color-text-faint)] hover:text-[color:var(--color-text)]"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const next = useRef(1)

  const show = useCallback<ToastApi['show']>((message, options = {}) => {
    const id = next.current++
    setItems((current) => [...current.slice(-3), { id, tone: options.tone ?? 'success', message, detail: options.detail }])
  }, [])

  const done = useCallback((id: number) => setItems((current) => current.filter((item) => item.id !== id)), [])
  const api = useMemo(() => ({ show }), [show])

  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(
        <div
          aria-live="polite"
          className="pointer-events-none fixed bottom-[max(1rem,env(safe-area-inset-bottom))] left-4 right-4 z-[90] flex flex-col items-stretch gap-2 sm:left-auto sm:w-96"
        >
          {items.map((item) => (
            <Toast key={item.id} item={item} onDone={done} />
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  )
}

export function useToast(): ToastApi {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used within ToastProvider')
  return context
}
