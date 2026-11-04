import { useId, type ReactNode } from 'react'

/** A line of the month-end balances, drawn as a soft area on the hero. Pure decoration over figures the page already shows. */
function Trend({ values }: { values: number[] }) {
  const id = useId().replace(/:/g, '')
  if (values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const step = 100 / (values.length - 1)
  const y = (value: number) => 36 - ((value - min) / span) * 30
  const line = values.map((value, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(2)},${y(value).toFixed(2)}`).join(' ')
  return (
    <svg viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true" className="h-24 w-full">
      <defs>
        <linearGradient id={`trend-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#fff" stopOpacity={0.35} />
          <stop offset="100%" stopColor="#fff" stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={`${line} L100,40 L0,40 Z`} fill={`url(#trend-${id})`} />
      <path d={line} fill="none" stroke="#fff" strokeOpacity={0.9} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

/**
 * The bank's balance as the first thing on the page: the figure large on the accent, the month-end balances behind it as a line, and what the account is.
 * It shows what the plain panel shows (the balance, where it started, each account's balance, whether it is reconciled) and the same "Add entry" action.
 */
export function BalanceHero({
  eyebrow,
  balance,
  balanceText,
  note,
  trend,
  accounts,
  standing,
  action,
}: {
  eyebrow: string
  balance: number
  balanceText: string
  note: string
  trend: number[]
  accounts: { name: string; text: string }[]
  standing: ReactNode
  action: ReactNode
}) {
  return (
    <section aria-label="Balance" className="panel relative overflow-hidden !p-0 text-[color:var(--orion-on-primary)]" style={{ backgroundImage: 'var(--orion-highlight-fill)' }}>
      <span className="lumen-orb pointer-events-none absolute -right-10 -top-14 h-56 w-56 rounded-full bg-white/20 blur-2xl" aria-hidden="true" />
      <div className="relative flex flex-wrap items-start justify-between gap-4 p-6 sm:p-8">
        <div className="min-w-0">
          <p className="text-xs font-bold uppercase tracking-[0.12em] opacity-85">{eyebrow}</p>
          <p className={`mt-2 font-display text-4xl font-semibold tabular-nums leading-none tracking-tight sm:text-5xl ${balance < 0 ? 'text-rose-100' : ''}`} aria-label={`Balance ${balanceText}`}>
            {balanceText}
          </p>
          <p className="mt-2 text-sm opacity-85">{note}</p>
          {accounts.length > 0 && (
            <ul className="mt-3 flex flex-wrap gap-2">
              {accounts.map((a) => (
                <li key={a.name} className="rounded-full bg-white/20 px-3 py-1 text-sm backdrop-blur">
                  <span className="opacity-85">{a.name}</span> <span className="font-semibold tabular-nums">{a.text}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 rounded-2xl bg-white/90 px-3 py-2 text-[color:var(--color-text)] shadow-card">{standing}</div>
        </div>
        {action}
      </div>
      <div className="relative -mt-2">
        <Trend values={trend} />
      </div>
    </section>
  )
}
