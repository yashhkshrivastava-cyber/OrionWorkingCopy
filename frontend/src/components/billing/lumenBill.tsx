import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { ArrowDown, ArrowUp, Check, Trash2 } from 'lucide-react'
import { money, type LineInput } from '../../billing/billCalc'
import type { LineSetup } from '../../types'
import { Input } from '../ui/Field'
import { LineFields } from './BillLinesEditor'

export type Step = { id: string; label: string; done: boolean }

/** The parts of the bill in the order they are filled in. Each shows whether it is complete and takes you to it. */
export function StepBar({ steps }: { steps: Step[] }) {
  return (
    <nav aria-label="Parts of the bill" className="scroll-quiet -mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
      {steps.map((step, index) => (
        <button
          key={step.id}
          type="button"
          onClick={() => document.getElementById(`bill-step-${step.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
          className={`interactive inline-flex shrink-0 items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-semibold ${
            step.done ? 'border-transparent bg-positive-dim text-positive' : 'border-[color:var(--color-border)] bg-[color:color-mix(in_srgb,var(--orion-surface)_70%,transparent)] text-[color:var(--color-text-muted)] hover:border-[color:var(--color-accent)]'
          }`}
        >
          <span className={`grid h-5 w-5 place-items-center rounded-full text-[11px] font-bold ${step.done ? 'bg-positive text-on-primary' : 'bg-muted text-[color:var(--color-text-muted)]'}`}>
            {step.done ? <Check className="h-3 w-3" strokeWidth={3} /> : index + 1}
          </span>
          {step.label}
        </button>
      ))}
    </nav>
  )
}

/** A part of the bill as a numbered card. */
export function StepCard({ id, number, title, hint, children }: { id: string; number: number; title: string; hint?: string; children: ReactNode }) {
  return (
    <section id={`bill-step-${id}`} className="scroll-mt-4 rounded-[1.75rem] border border-[color:var(--color-border)] bg-[color:var(--orion-surface-fill)] p-5 shadow-card">
      <header className="mb-4 flex items-start gap-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-bold text-on-primary [background-image:var(--orion-primary-fill)]">{number}</span>
        <div className="min-w-0">
          <h2 className="font-display text-lg font-semibold leading-tight">{title}</h2>
          {hint && <p className="t-caption mt-0.5 text-[color:var(--color-text-muted)]">{hint}</p>}
        </div>
      </header>
      <div className="space-y-3">{children}</div>
    </section>
  )
}

/** One line of the bill as a card: what, how many, at what rate, and what it comes to. It can be moved up or down. */
export function LineCard({
  index,
  count,
  line,
  setup,
  amount,
  onChange,
  onRemove,
  onMove,
}: {
  index: number
  count: number
  line: LineInput
  setup: LineSetup
  amount: number | null
  onChange: (patch: Partial<LineInput>) => void
  onRemove: () => void
  onMove: (direction: -1 | 1) => void
}) {
  return (
    <div className="group rounded-3xl border border-[color:var(--color-border)] bg-[color:color-mix(in_srgb,var(--orion-surface)_75%,transparent)] p-3">
      <div className="flex items-start gap-2">
        <span className="mt-1 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-accent-dim text-xs font-bold text-accent">{index + 1}</span>
        <Input aria-label={`Line ${index + 1} description`} placeholder="Skilled (Supervisor)" value={line.particulars} onChange={(e) => onChange({ particulars: e.target.value })} />
        <div className="flex shrink-0 flex-col">
          <button type="button" aria-label={`Move line ${index + 1} up`} disabled={index === 0} onClick={() => onMove(-1)} className="interactive rounded-full p-1 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)] disabled:opacity-30">
            <ArrowUp className="h-3.5 w-3.5" />
          </button>
          <button type="button" aria-label={`Move line ${index + 1} down`} disabled={index === count - 1} onClick={() => onMove(1)} className="interactive rounded-full p-1 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)] disabled:opacity-30">
            <ArrowDown className="h-3.5 w-3.5" />
          </button>
        </div>
        <button type="button" aria-label={`Remove line ${index + 1}`} onClick={onRemove} className="interactive mt-1 rounded-full p-2 text-[color:var(--color-text-faint)] hover:bg-negative-dim hover:text-negative">
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-2 pl-9">
        <LineFields index={index} line={line} setup={setup} amount={amount} onChange={onChange} />
      </div>
    </div>
  )
}

const PAPER_PX = 794

/** The bill as it will print, on a desk: it shrinks to fit the space (or shows at full size) and never changes its own look. */
export function PaperDesk({ children }: { children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null)
  const [fit, setFit] = useState(true)
  const [scale, setScale] = useState(1)

  useLayoutEffect(() => {
    const node = box.current
    if (!node) return
    const measure = () => setScale(Math.min(1, Math.max(0.4, (node.clientWidth - 32) / PAPER_PX)))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  return (
    <section aria-label="The bill as it will print" className="rounded-[1.75rem] border border-[color:var(--color-border)] bg-[color:color-mix(in_srgb,var(--orion-muted)_70%,transparent)] p-3 sm:p-4">
      <div className="mb-3 flex items-center justify-between gap-2 px-1">
        <p className="eyebrow">Preview</p>
        <div role="group" aria-label="Preview size" className="flex rounded-full border border-[color:var(--color-border)] bg-surface p-0.5">
          {(
            [
              [true, 'Fit'],
              [false, 'Full size'],
            ] as const
          ).map(([value, label]) => (
            <button key={label} type="button" aria-pressed={fit === value} onClick={() => setFit(value)} className={`interactive rounded-full px-3 py-1 text-xs font-semibold ${fit === value ? 'text-on-primary [background-image:var(--orion-primary-fill)]' : 'text-[color:var(--color-text-muted)]'}`}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <div ref={box} className="overflow-x-auto">
        <div style={{ zoom: fit ? scale : 1 }}>{children}</div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------------------------------- viewing a bill

/** How much of the bill has been settled, as a ring with the share in the middle. */
export function CollectionRing({ share }: { share: number }) {
  const clamped = Math.max(0, Math.min(1, share))
  const radius = 44
  const circle = 2 * Math.PI * radius
  return (
    <div className="relative h-32 w-32 shrink-0" role="img" aria-label={`${Math.round(clamped * 100)} percent of the bill is settled`}>
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
        <circle cx="50" cy="50" r={radius} fill="none" stroke="var(--orion-muted)" strokeWidth="9" />
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          stroke="var(--orion-primary)"
          strokeWidth="9"
          strokeLinecap="round"
          strokeDasharray={circle}
          strokeDashoffset={circle * (1 - clamped)}
          style={{ transition: 'stroke-dashoffset 900ms cubic-bezier(0.2, 0.9, 0.2, 1)' }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <p className="font-display text-2xl font-semibold leading-none tabular-nums">{Math.round(clamped * 100)}%</p>
          <p className="t-caption mt-0.5 text-[color:var(--color-text-muted)]">settled</p>
        </div>
      </div>
    </div>
  )
}

function Money({ label, value, tone }: { label: string; value: number; tone?: 'positive' | 'negative' }) {
  return (
    <div>
      <p className="t-caption text-[color:var(--color-text-muted)]">{label}</p>
      <p className={`font-display text-lg font-semibold tabular-nums ${tone === 'positive' ? 'text-positive' : tone === 'negative' ? 'text-negative' : ''}`}>₹ {money(value)}</p>
    </div>
  )
}

/**
 * The top of a bill: its number, whose it is and where it stands, and a ring of how much has been settled with the figures behind it. Everything is read
 * from the bill; nothing here records anything.
 */
export function BillHero({
  number,
  status,
  who,
  where,
  version,
  grandTotal,
  settled,
  received,
  heldBack,
  credited,
  remaining,
  cancelled,
}: {
  number: string
  status: string
  who: string
  where: string
  version: string
  grandTotal: number
  settled: number
  received: number
  heldBack: number
  credited: number
  remaining: number
  cancelled: boolean
}) {
  const share = grandTotal > 0 ? settled / grandTotal : 0
  const chip = cancelled ? 'bg-negative-dim text-negative' : remaining <= 0.005 ? 'bg-positive-dim text-positive' : settled > 0 ? 'bg-warning-dim text-warning' : 'bg-accent-dim text-accent'
  return (
    <section aria-label="Bill summary" className="panel relative overflow-hidden !p-6" style={{ backgroundImage: 'radial-gradient(60% 120% at 0% 0%, color-mix(in srgb, var(--orion-primary) 14%, transparent), transparent 70%)' }}>
      <div className="flex flex-wrap items-center gap-x-8 gap-y-5">
        <div className="min-w-0 flex-1 basis-72">
          <p className="eyebrow">Tax invoice</p>
          <h1 className="lumen-title font-display mt-1 text-3xl font-semibold leading-none tabular-nums">{number}</h1>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-3 py-1 text-xs font-bold ${chip}`}>{status}</span>
            <span className="rounded-full bg-muted px-3 py-1 text-xs font-semibold text-[color:var(--color-text-muted)]">{version}</span>
          </div>
          <p className="mt-3 font-display text-lg font-semibold">{who}</p>
          <p className="t-small text-[color:var(--color-text-muted)]">{where}</p>
        </div>
        {!cancelled && (
          <div className="flex flex-wrap items-center gap-6">
            <CollectionRing share={share} />
            <div className="grid grid-cols-2 gap-x-8 gap-y-3">
              <Money label="Billed" value={grandTotal} />
              <Money label="Left to receive" value={remaining} tone={remaining > 0.005 ? 'negative' : 'positive'} />
              <Money label="Received in the bank" value={received} />
              {heldBack > 0 ? <Money label="Held back (TDS and the like)" value={heldBack} /> : <Money label="Credited" value={credited} />}
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
