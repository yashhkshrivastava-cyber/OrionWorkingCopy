import type { Category } from '../../types'
import { SERIES, count } from './format'
import { Empty } from './CategoryBar'

/**
 * Pipeline stages as a tapered funnel. Built from divs rather than a chart
 * library so the whole row is a comfortable click target.
 */
export function StageFunnel({
  data,
  selected,
  onSelect,
  caption = 'open opportunities',
}: {
  data: Category[]
  selected?: string
  onSelect?: (code: string) => void
  caption?: string
}) {
  if (!data.length) return <Empty height={240} message="No opportunities in this selection." />

  const max = Math.max(...data.map((entry) => entry.value), 1)
  const total = data.reduce((sum, entry) => sum + entry.value, 0)

  return (
    <div className="space-y-2.5 px-4 py-2">
      {data.map((entry, index) => {
        const width = 32 + (entry.value / max) * 68
        const isDim = selected && selected !== entry.code
        return (
          <button
            key={entry.code}
            type="button"
            onClick={() => onSelect?.(entry.code)}
            disabled={!onSelect}
            className={`group block w-full text-left ${onSelect ? '' : 'cursor-default'}`}
          >
            <div className="mb-1 flex items-baseline justify-between text-xs">
              <span className={`font-medium ${isDim ? 'text-[color:var(--color-text-faint)]' : 'text-[color:var(--color-text)]'}`}>
                {entry.label}
              </span>
              <span className={isDim ? 'text-[color:var(--color-text-faint)]' : 'text-[color:var(--color-text-muted)]'}>
                {count(entry.value)} · {total ? Math.round((entry.value / total) * 100) : 0}%
              </span>
            </div>
            <div className="flex justify-center">
              <div
                className="h-8 rounded-lg transition-all duration-300 group-hover:brightness-110"
                style={{
                  width: `${width}%`,
                  background: SERIES.pipeline,
                  // Later stages fade a little, so the funnel reads top to bottom.
                  opacity: isDim ? 0.2 : Math.max(0.5, 1 - index * 0.08),
                }}
              />
            </div>
          </button>
        )
      })}
      <p className="pt-1 text-center text-[11px] text-[color:var(--color-text-faint)]">
        {count(total)} {caption} across {data.length} stages
      </p>
    </div>
  )
}
