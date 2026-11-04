import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate } from 'react-router-dom'
import { House, Search, X } from 'lucide-react'
import { useTabMemory } from '../../context/TabMemoryContext'
import { useTasks } from '../../context/TasksContext'
import { useDialog } from '../../hooks/useDialog'
import { usePresence } from '../../hooks/usePresence'
import type { User } from '../../types'
import { AREA_BLURB, NAV_GROUPS, hueVar } from '../nav/navigation'

/**
 * Every place in Orion as one grid of coloured tiles, with a search box on top. Type to narrow it, Enter opens the first match, Escape closes.
 * It is the same list as the dock (what this person may use), shown all at once.
 */
export function LumenLauncher({ open, user, unread, onClose }: { open: boolean; user: User; unread: number; onClose: () => void }) {
  const { present, leaving } = usePresence(open)
  const panel = useRef<HTMLDivElement>(null)
  const last = useTabMemory()
  const navigate = useNavigate()
  const { me } = useTasks()
  const [query, setQuery] = useState('')
  useDialog(panel, open, onClose)

  useEffect(() => {
    if (open) setQuery('')
  }, [open])

  const counts: Record<string, number> = { messages: unread, tasks: me.unread + me.attention, admin: user.pending_signups ?? 0 }
  const groups = useMemo(() => {
    const text = query.trim().toLowerCase()
    return NAV_GROUPS.map((group) => ({
      label: group.label,
      items: group.items.filter((item) => item.visible(user) && (!text || `${item.label} ${AREA_BLURB[item.area]}`.toLowerCase().includes(text))),
    })).filter((group) => group.items.length)
  }, [query, user])

  if (!present) return null
  const first = groups[0]?.items[0]

  return createPortal(
    <div className="fixed inset-0 z-[90] flex items-start justify-center p-3 pt-[8vh] sm:p-8 sm:pt-[10vh]">
      <button type="button" tabIndex={-1} aria-label="Close" onClick={onClose} className={`${leaving ? 'backdrop-out' : 'backdrop-in'} absolute inset-0 bg-scrim backdrop-blur-md`} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label="All spaces"
        className={`${leaving ? 'pop-out' : 'pop-in'} overlay relative flex max-h-[84vh] w-full max-w-4xl flex-col overflow-hidden rounded-[2rem] border border-[color:var(--color-border)]`}
      >
        <div className="flex items-center gap-3 border-b border-[color:var(--color-border)] px-5 py-4">
          <Search className="h-5 w-5 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && first) {
                onClose()
                navigate(last[first.area])
              }
            }}
            placeholder="Where to? Billing, Tasks, Documents…"
            aria-label="Find a space"
            className="font-display min-w-0 flex-1 bg-transparent text-xl text-[color:var(--color-text)] placeholder:text-[color:var(--color-text-faint)] !border-0 !bg-transparent !ring-0"
          />
          <button type="button" onClick={onClose} aria-label="Close" className="interactive rounded-full p-2 text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="scroll-quiet min-h-0 flex-1 space-y-6 overflow-y-auto p-5">
          {!query.trim() && (
            <Link to="/" onClick={onClose} className="panel interactive flex items-center gap-4 !p-4 hover:shadow-raised">
              <span className="grid h-12 w-12 place-items-center rounded-2xl bg-accent-dim text-accent">
                <House className="h-6 w-6" />
              </span>
              <span>
                <span className="font-display block text-base font-semibold">Today</span>
                <span className="t-caption">Your day at a glance</span>
              </span>
            </Link>
          )}
          {groups.map((group) => (
            <section key={group.label}>
              <h3 className="eyebrow mb-2 px-1">{group.label}</h3>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {group.items.map((item) => {
                  const Icon = item.icon
                  const count = counts[item.area] ?? 0
                  return (
                    <Link
                      key={item.area}
                      to={last[item.area]}
                      onClick={onClose}
                      style={{ '--hue': hueVar(item.area) } as React.CSSProperties}
                      className="panel interactive group flex items-center gap-4 !p-4 hover:shadow-raised"
                    >
                      <span className="lumen-chip relative grid h-12 w-12 shrink-0 place-items-center rounded-2xl">
                        <Icon className="h-6 w-6" />
                        {count > 0 && <span className="absolute -right-1 -top-1 rounded-full bg-amber px-1.5 text-[10px] font-bold leading-4 text-ink">{count > 99 ? '99+' : count}</span>}
                      </span>
                      <span className="min-w-0">
                        <span className="font-display block truncate text-base font-semibold">{item.label}</span>
                        <span className="t-caption line-clamp-2">{AREA_BLURB[item.area]}</span>
                      </span>
                    </Link>
                  )
                })}
              </div>
            </section>
          ))}
          {groups.length === 0 && <p className="py-10 text-center text-sm text-[color:var(--color-text-muted)]">Nothing matches “{query}”.</p>}
        </div>
      </div>
    </div>,
    document.body,
  )
}
