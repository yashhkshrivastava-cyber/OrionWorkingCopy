import type { ReactNode } from 'react'
import { ChartNoAxesCombined, Database, ReceiptText } from 'lucide-react'
import { BrandMark } from './BrandMark'
import { ThemeToggle } from './ThemeToggle'
import { useLumen } from '../lumen/useLumen'

const POINTS = [
  { icon: ChartNoAxesCombined, text: 'Dashboards for revenue, delivery, people, pipeline and fleet' },
  { icon: Database, text: 'Operational records and the warehouse built from them' },
  { icon: ReceiptText, text: 'Tax invoices raised, tracked and versioned per case' },
]

/**
 * The frame around the signed-out pages: a brand panel beside the form on wide screens,
 * and the form alone on a phone.
 */
export function AuthFrame({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: ReactNode
}) {
  const lumen = useLumen()
  if (lumen) {
    return (
      <div className="app-canvas relative flex min-h-dvh items-center justify-center overflow-hidden px-4 py-8">
        <div className="absolute right-4 top-[max(1rem,env(safe-area-inset-top))] z-10">
          <ThemeToggle />
        </div>
        <div className="page-enter panel relative grid w-full max-w-5xl overflow-hidden !p-0 lg:grid-cols-[1.1fr_1fr]">
          <aside
            className="relative flex flex-col justify-between gap-10 p-7 text-[color:var(--orion-on-primary)] sm:p-9 lg:p-12"
            style={{ backgroundImage: 'var(--orion-highlight-fill)' }}
          >
            <span className="lumen-orb pointer-events-none absolute -right-16 -top-20 h-72 w-72 rounded-full bg-white/20 blur-3xl" aria-hidden="true" />
            <span className="lumen-orb pointer-events-none absolute -bottom-24 -left-10 h-64 w-64 rounded-full bg-white/10 blur-3xl max-lg:hidden" aria-hidden="true" />
            <div className="relative flex items-center gap-3">
              <BrandMark size={40} />
              <span className="leading-tight">
                <span className="font-display block text-lg font-bold">Prakash Securities</span>
                <span className="block text-xs opacity-80">Orion workspace</span>
              </span>
            </div>
            <div className="relative max-lg:hidden">
              <h2 className="font-display max-w-md text-4xl font-semibold leading-[1.1] xl:text-5xl">The company&apos;s numbers, records and bills in one place.</h2>
              <ul className="mt-8 space-y-3">
                {POINTS.map(({ icon: Icon, text }) => (
                  <li key={text} className="flex items-center gap-3 rounded-2xl bg-white/15 px-4 py-3 text-sm backdrop-blur">
                    <Icon className="h-5 w-5 shrink-0" aria-hidden="true" />
                    <span>{text}</span>
                  </li>
                ))}
              </ul>
            </div>
            <p className="relative text-xs opacity-80 max-lg:hidden">Access is granted by an administrator.</p>
          </aside>

          <main className="flex flex-col justify-center p-6 sm:p-10 lg:p-12">
            <h1 className="font-display text-3xl font-semibold leading-tight sm:text-4xl">{title}</h1>
            <p className="mt-2 text-sm text-[color:var(--color-text-muted)]">{subtitle}</p>
            <div className="mt-7">{children}</div>
          </main>
        </div>
      </div>
    )
  }

  return (
    <div className="app-canvas flex min-h-dvh">
      <aside className="relative hidden w-[44%] max-w-xl shrink-0 flex-col justify-between overflow-hidden bg-rail p-10 text-rail-strong lg:flex xl:p-14">
        <div
          className="pointer-events-none absolute -right-24 -top-24 h-96 w-96 rounded-full bg-rail-accent/20 blur-3xl"
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute inset-0 opacity-40 [background-image:radial-gradient(color-mix(in_srgb,var(--orion-rail-strong)_14%,transparent)_1px,transparent_1px)] [background-size:22px_22px] [mask-image:linear-gradient(180deg,#000,transparent_75%)]"
          aria-hidden="true"
        />
        <div className="relative flex items-center gap-3">
          <BrandMark size={36} />
          <span className="leading-tight">
            <span className="font-display block text-lg font-bold">Prakash Securities</span>
            <span className="block text-xs text-[color:var(--color-rail-text-faint)]">Orion workspace</span>
          </span>
        </div>
        <div className="relative">
          <h2 className="font-display max-w-md text-3xl font-bold leading-tight xl:text-4xl">
            The company&apos;s numbers, records and bills in one workspace.
          </h2>
          <ul className="mt-8 space-y-4">
            {POINTS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-start gap-3 text-sm text-[color:var(--color-rail-text)]">
                <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-rail-active text-rail-accent">
                  <Icon className="h-4 w-4" />
                </span>
                <span className="pt-1.5">{text}</span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-[color:var(--color-rail-text-faint)]">
          Access is granted by an administrator.
        </p>
      </aside>

      <main className="relative flex min-w-0 flex-1 items-center justify-center px-4 py-10">
        <div className="absolute right-4 top-[max(1rem,env(safe-area-inset-top))]">
          <ThemeToggle />
        </div>
        <div className="page-enter w-full max-w-md">
          <div className="mb-6">
            <BrandMark size={44} className="mb-4 lg:hidden" />
            <h1 className="t-h1 text-[color:var(--color-text)]">{title}</h1>
            <p className="mt-1.5 text-sm text-[color:var(--color-text-muted)]">{subtitle}</p>
          </div>
          <div className="panel p-6">{children}</div>
        </div>
      </main>
    </div>
  )
}
