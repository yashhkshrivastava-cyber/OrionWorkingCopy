import { ArrowRight, type LucideIcon } from 'lucide-react'
import { useLumen } from '../../lumen/useLumen'

/** The two colours each tone is washed with in Lumen. */
const LUMEN_TONES = {
  teal: ['indigo', 'cyan'],
  amber: ['amber', 'coral'],
  violet: ['violet', 'pink'],
} as const

const TONES = {
  teal: {
    icon: 'bg-accent-dim text-accent',
    badge: 'bg-accent-dim text-accent',
    hover: 'hover:border-accent',
    cta: 'text-accent',
  },
  amber: {
    icon: 'bg-warning-dim text-warning',
    badge: 'bg-warning-dim text-warning',
    hover: 'hover:border-warning',
    cta: 'text-warning',
  },
  violet: {
    icon: 'bg-violet-dim text-violet',
    badge: 'bg-violet-dim text-violet',
    hover: 'hover:border-violet',
    cta: 'text-violet',
  },
} as const

/** A large choice between ways of working. The whole card is the button. */
export function IntentCard({
  tone,
  icon,
  badge,
  title,
  body,
  chips,
  cta,
  onClick,
}: {
  tone: keyof typeof TONES
  icon: LucideIcon
  badge: string
  title: string
  body: string
  chips: string[]
  cta: string
  onClick: () => void
}) {
  const Icon = icon
  const colors = TONES[tone]
  const lumen = useLumen()

  if (lumen) {
    const [from, to] = LUMEN_TONES[tone]
    return (
      <button
        type="button"
        onClick={onClick}
        style={{ '--from': `var(--lumen-${from})`, '--to': `var(--lumen-${to})` } as React.CSSProperties}
        className="lumen-intent panel group relative flex flex-col overflow-hidden !p-0 text-left"
      >
        <div className="relative h-36 overflow-hidden px-6 pt-5 [background:linear-gradient(135deg,var(--from),var(--to))]">
          <span className="lumen-orb pointer-events-none absolute -right-8 -top-10 h-44 w-44 rounded-full bg-white/25 blur-2xl" aria-hidden="true" />
          <span className="lumen-orb pointer-events-none absolute -bottom-12 left-1/3 h-36 w-36 rounded-full bg-white/20 blur-2xl [animation-delay:-3s]" aria-hidden="true" />
          <div className="relative flex items-start justify-between gap-3">
            <span className="grid h-14 w-14 place-items-center rounded-2xl bg-white/25 text-white shadow-lg backdrop-blur transition-transform duration-500 group-hover:scale-110 group-hover:-rotate-6">
              <Icon className="h-7 w-7" />
            </span>
            <span className="rounded-full bg-white/25 px-3 py-1 text-[11px] font-bold text-white backdrop-blur">{badge}</span>
          </div>
        </div>
        <div className="flex flex-1 flex-col p-6">
          <h2 className="font-display text-2xl font-semibold">{title}</h2>
          <p className="mt-1.5 text-sm leading-relaxed text-[color:var(--color-text-muted)]">{body}</p>
          <div className="mt-4 flex flex-wrap gap-1.5">
            {chips.map((chip) => (
              <span key={chip} className="rounded-full bg-muted px-3 py-1 text-[11px] font-semibold text-[color:var(--color-text-muted)]">
                {chip}
              </span>
            ))}
          </div>
          <span className="mt-auto inline-flex w-fit items-center gap-2 pt-6 text-sm font-bold [color:color-mix(in_srgb,var(--from)_80%,var(--orion-text))]">
            {cta}
            <span className="grid h-8 w-8 place-items-center rounded-full text-white transition-transform duration-300 group-hover:translate-x-1 [background:linear-gradient(135deg,var(--from),var(--to))]">
              <ArrowRight className="h-4 w-4" />
            </span>
          </span>
        </div>
      </button>
    )
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={`intent-hot panel group flex flex-col p-5 text-left sm:p-6 ${colors.hover}`}
    >
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className={`hot-icon flex h-11 w-11 items-center justify-center rounded-xl ${colors.icon}`}>
          <Icon className="h-5 w-5" />
        </div>
        <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${colors.badge}`}>{badge}</span>
      </div>
      <h2 className="t-h2">{title}</h2>
      <p className="mt-1.5 text-sm leading-relaxed text-[color:var(--color-text-muted)]">{body}</p>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {chips.map((chip) => (
          <span
            key={chip}
            className="rounded-full border border-[color:var(--color-border)] bg-muted/60 px-2.5 py-0.5 text-[11px] font-medium text-[color:var(--color-text-muted)]"
          >
            {chip}
          </span>
        ))}
      </div>
      <p className={`hot-cta mt-auto inline-flex items-center gap-1.5 pt-5 text-sm font-semibold ${colors.cta}`}>
        {cta}
        <ArrowRight className="h-4 w-4" />
      </p>
    </button>
  )
}
