import { useContext, type ReactNode } from 'react'
import { ChevronLeft } from 'lucide-react'
import { WorkbenchCollapseContext } from './WorkbenchChrome'
import { LumenCatalog } from '../../lumen/LumenCatalog'
import { useLumen } from '../../lumen/useLumen'

export type CatalogItem = { id: string; label: string; meta?: string }

export type CatalogGroup = { label: string; icon?: ReactNode; items: CatalogItem[] }

/** The tone marks which store the catalog belongs to; it only colours the selected row. */
const TONE = {
  teal: { active: 'bg-accent-dim text-accent', bar: 'bg-accent' },
  amber: { active: 'bg-warning-dim text-warning', bar: 'bg-warning' },
  violet: { active: 'bg-violet-dim text-violet', bar: 'bg-violet' },
} as const

const IDLE = 'text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]'

export function WorkbenchCatalog({
  tone = 'teal',
  title = 'Catalog',
  groups,
  selected,
  onSelect,
  onCollapse,
}: {
  tone?: keyof typeof TONE
  title?: string
  groups: CatalogGroup[]
  selected: string
  onSelect: (id: string) => void
  onCollapse?: () => void
}) {
  const colors = TONE[tone]
  const collapseFromStage = useContext(WorkbenchCollapseContext).collapseCatalog
  const collapse = onCollapse ?? collapseFromStage
  const lumen = useLumen()
  if (lumen) return <LumenCatalog title={title} groups={groups} selected={selected} onSelect={onSelect} onCollapse={collapse} />
  return (
    <section className="panel flex h-full min-h-0 flex-col overflow-hidden p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="eyebrow px-2">{title}</p>
        {collapse ? (
          <button
            type="button"
            onClick={collapse}
            aria-label="Collapse catalog"
            title="Collapse catalog"
            className="flex h-7 w-7 items-center justify-center rounded-lg text-[color:var(--color-text-faint)] transition-colors hover:bg-muted hover:text-[color:var(--color-text)]"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
      <div className="mt-2 min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
        {groups.map((group) => (
          <div key={group.label}>
            <p className="mb-1 flex items-center gap-1.5 px-2 text-xs font-semibold text-[color:var(--color-text)]">
              {group.icon}
              {group.label}
            </p>
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const active = item.id === selected
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onSelect(item.id)}
                    aria-current={active ? 'true' : undefined}
                    className={`relative flex w-full items-center justify-between gap-3 rounded-lg px-2.5 py-1.5 text-left transition-colors ${
                      active ? `${colors.active} font-semibold` : IDLE
                    }`}
                  >
                    {active && <span className={`absolute left-0 h-4 w-0.5 rounded-r ${colors.bar}`} aria-hidden="true" />}
                    <span className="truncate text-sm">{item.label}</span>
                    {item.meta ? (
                      <span className={`shrink-0 text-[11px] tabular-nums ${active ? 'opacity-80' : 'text-[color:var(--color-text-faint)]'}`}>
                        {item.meta}
                      </span>
                    ) : null}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
