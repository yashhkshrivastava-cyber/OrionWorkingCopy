import { createContext, useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'

export const WorkbenchCollapseContext = createContext<{
  collapseCatalog?: () => void
  collapsePreview?: () => void
}>({})

const CATALOG_KEY = 'orion.workbench.catalog'
const PREVIEW_KEY = 'orion.workbench.preview'

function readOpen(key: string, fallback: boolean) {
  try {
    const raw = sessionStorage.getItem(key)
    if (raw === '1') return true
    if (raw === '0') return false
  } catch {
    /* ignore */
  }
  return fallback
}

function writeOpen(key: string, value: boolean) {
  try {
    sessionStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* ignore */
  }
}

function RestoreChip({
  label,
  onClick,
  className = '',
}: {
  label: string
  onClick: () => void
  className?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`Show ${label}`}
      title={`Show ${label}`}
      className={`interactive inline-flex h-7 shrink-0 items-center gap-1 rounded-full border border-[color:var(--color-border)] bg-surface px-2.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-[color:var(--color-text-muted)] shadow-card hover:border-[color:var(--color-border-strong)] hover:text-[color:var(--color-text)] ${className}`}
    >
      <ChevronRight className="h-3 w-3" />
      {label}
    </button>
  )
}

/** The tone marks which store the trail belongs to, as a dot before the current place. */
const TONE = {
  teal: 'bg-accent',
  amber: 'bg-warning',
  violet: 'bg-violet',
} as const

export function WorkbenchBack({ to = '/data', label = 'Data management' }: {
  to?: string
  label?: string
  tone?: keyof typeof TONE
}) {
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-1 text-sm font-medium text-[color:var(--color-text-muted)] transition-colors hover:text-[color:var(--color-text)]"
    >
      <ChevronLeft className="h-4 w-4" />
      {label}
    </Link>
  )
}

export function WorkbenchPlace({
  tone = 'teal',
  here,
  item,
  backTo = '/data',
  backLabel = 'Data management',
}: {
  tone?: keyof typeof TONE
  here: string
  item?: string
  backTo?: string
  backLabel?: string
}) {
  return (
    <nav className="flex shrink-0 flex-wrap items-center gap-1.5 text-sm" aria-label="Location">
      <WorkbenchBack to={backTo} label={backLabel} tone={tone} />
      <span className="text-[color:var(--color-text-faint)]">/</span>
      <h1 className="inline-flex items-center gap-2 font-sans text-sm font-semibold tracking-normal text-[color:var(--color-text)]">
        <span className={`h-1.5 w-1.5 rounded-full ${TONE[tone]}`} aria-hidden="true" />
        {here}
      </h1>
      {item ? (
        <>
          <span className="text-[color:var(--color-text-faint)]">/</span>
          <span className="text-sm text-[color:var(--color-text)]">{item}</span>
        </>
      ) : null}
    </nav>
  )
}

export function WorkbenchShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-[calc(100dvh-5rem)] min-h-[32rem] flex-col gap-3 overflow-hidden">{children}</div>
  )
}

export function WorkbenchStage({
  catalog,
  main,
  aside,
}: {
  catalog: ReactNode
  main: ReactNode
  aside?: ReactNode
}) {
  const [catalogOpen, setCatalogOpen] = useState(() => readOpen(CATALOG_KEY, true))
  const [asideOpen, setAsideOpen] = useState(() => readOpen(PREVIEW_KEY, true))

  useEffect(() => writeOpen(CATALOG_KEY, catalogOpen), [catalogOpen])
  useEffect(() => writeOpen(PREVIEW_KEY, asideOpen), [asideOpen])

  return (
    <WorkbenchCollapseContext.Provider
      value={{
        collapseCatalog: () => setCatalogOpen(false),
        collapsePreview: aside ? () => setAsideOpen(false) : undefined,
      }}
    >
      <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row">
        {catalogOpen ? <div className="hidden h-full w-[18.5rem] shrink-0 lg:block">{catalog}</div> : null}

        {catalogOpen ? (
          <div className="lg:hidden">
            <button
              type="button"
              className="fixed inset-0 z-20 bg-scrim backdrop-in"
              aria-label="Close catalog"
              onClick={() => setCatalogOpen(false)}
            />
            <div className="fixed inset-y-3 left-3 z-30 w-[18.5rem] overflow-hidden drawer-in">{catalog}</div>
          </div>
        ) : (
          <RestoreChip
            label="Catalog"
            onClick={() => setCatalogOpen(true)}
            className="self-start lg:hidden"
          />
        )}

        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2">
          {!catalogOpen && aside && !asideOpen ? (
            <div className="hidden w-full shrink-0 items-center justify-between lg:flex">
              <RestoreChip label="Catalog" onClick={() => setCatalogOpen(true)} />
              <RestoreChip label="Records" onClick={() => setAsideOpen(true)} />
            </div>
          ) : !catalogOpen ? (
            <RestoreChip label="Catalog" onClick={() => setCatalogOpen(true)} className="hidden self-start lg:inline-flex" />
          ) : aside && !asideOpen ? (
            <RestoreChip label="Records" onClick={() => setAsideOpen(true)} className="hidden self-end lg:inline-flex" />
          ) : null}
          <div className="min-h-0 flex-1 overflow-hidden">{main}</div>
          {aside && asideOpen ? <div className="h-[42%] min-h-[12rem] overflow-hidden lg:hidden">{aside}</div> : null}
          {aside && !asideOpen ? (
            <RestoreChip
              label="Records"
              onClick={() => setAsideOpen(true)}
              className="self-start lg:hidden"
            />
          ) : null}
        </div>

        {aside && asideOpen ? <div className="hidden h-full w-[22rem] shrink-0 lg:block">{aside}</div> : null}
      </div>
    </WorkbenchCollapseContext.Provider>
  )
}

export function WorkbenchPanel({
  children,
  className = '',
  fill = false,
}: {
  children: ReactNode
  className?: string
  fill?: boolean
}) {
  return (
    <section
      className={`panel ${fill ? 'flex h-full min-h-0 w-full flex-col overflow-hidden' : 'p-5 sm:p-6'} ${className}`}
    >
      {children}
    </section>
  )
}
