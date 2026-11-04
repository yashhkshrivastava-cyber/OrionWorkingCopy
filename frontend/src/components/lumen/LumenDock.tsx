import { Link, NavLink, useLocation } from 'react-router-dom'
import { House, LayoutGrid, LifeBuoy, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { useTabMemory, areaOf } from '../../context/TabMemoryContext'
import { useTasks } from '../../context/TasksContext'
import type { User } from '../../types'
import { BrandMark } from '../BrandMark'
import { NAV_GROUPS, hueVar } from '../nav/navigation'

const OPEN_KEY = 'orion-lumen-dock-open'

/** The dock starts open, with its labels; a person who folds it away keeps it folded. */
export function readDockOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) !== '0'
  } catch {
    return true
  }
}

/**
 * The navigation of the Lumen interface: a floating sidebar down the left edge. It is either open (an icon and its name for every area, in groups) or
 * folded to a slim column of the same icons, and it stays as it is until the person changes it with the button at the bottom: it never opens or closes
 * by itself, and the page beside it moves with it. Every item is one click from anywhere and remembers where you left it.
 */
export function LumenDock({ user, unread, open, onOpen, onLauncher, onRaiseRequest }: { user: User; unread: number; open: boolean; onOpen: (value: boolean) => void; onLauncher: () => void; onRaiseRequest: () => void }) {
  const location = useLocation()
  const last = useTabMemory()
  const current = areaOf(location.pathname)
  const { me } = useTasks()
  const counts: Record<string, number> = { messages: unread, tasks: me.unread + me.attention, admin: user.pending_signups ?? 0 }

  const toggle = () => {
    const next = !open
    try {
      localStorage.setItem(OPEN_KEY, next ? '1' : '0')
    } catch {
      /* the dock still changes for this visit */
    }
    onOpen(next)
    // charts measure their container: tell them once the sidebar has finished moving
    window.setTimeout(() => window.dispatchEvent(new Event('resize')), 380)
  }

  const row = 'lumen-dock-item relative flex w-full items-center gap-3 rounded-2xl p-1.5 text-left outline-none'
  const chip = 'lumen-chip relative grid h-10 w-10 shrink-0 place-items-center rounded-2xl'
  const label = 'lumen-dock-label min-w-0 flex-1 truncate text-sm font-semibold'
  const tip = (text: string) => (open ? undefined : text)

  return (
    <aside aria-label="Main" data-open={open} className="lumen-dock group fixed bottom-4 left-4 top-4 z-30 hidden flex-col overflow-hidden rounded-[2rem] border border-[color:var(--color-border)] bg-[color:var(--orion-surface-fill)] shadow-raised backdrop-blur-xl lg:flex">
      <Link to="/" title={tip('Orion home')} className="lumen-dock-brand flex shrink-0 items-center gap-3 px-3.5 pb-2 pt-4" aria-label="Orion home">
        <span className="lumen-orb grid h-10 w-10 shrink-0 place-items-center">
          <BrandMark size={32} />
        </span>
        <span className="lumen-dock-label min-w-0 leading-tight">
          <span className="font-display block truncate text-[15px] font-bold">Prakash Securities</span>
          <span className="block text-[11px] text-[color:var(--color-text-faint)]">Orion workspace</span>
        </span>
      </Link>

      <nav className="scroll-quiet min-h-0 flex-1 space-y-1 overflow-y-auto overflow-x-hidden px-2.5 py-2">
        <NavLink to="/" end title={tip('Today')} style={{ '--hue': 'var(--orion-accent)' } as React.CSSProperties} className={row} aria-label="Today">
          <span className={chip}>
            <House className="h-5 w-5" />
          </span>
          <span className={label}>Today</span>
        </NavLink>

        {NAV_GROUPS.map((group) => {
          const items = group.items.filter((item) => item.visible(user))
          if (!items.length) return null
          return (
            <div key={group.label} className="pt-2">
              <p className="lumen-dock-label eyebrow px-2 pb-1">{group.label}</p>
              <div className="lumen-dock-rule mx-3 mb-1 border-t border-[color:var(--color-border)]" aria-hidden="true" />
              {items.map((item) => {
                const Icon = item.icon
                const active = current === item.area
                const count = counts[item.area] ?? 0
                return (
                  <Link key={item.area} to={last[item.area]} title={tip(item.label)} aria-current={active ? 'page' : undefined} aria-label={item.label} style={{ '--hue': hueVar(item.area) } as React.CSSProperties} className={row}>
                    <span className={chip}>
                      <Icon className="h-5 w-5" />
                      {count > 0 && <span className="absolute -right-1 -top-1 min-w-4 rounded-full bg-amber px-1 text-center text-[9px] font-bold leading-4 text-ink ring-2 ring-[color:var(--color-surface)]">{count > 99 ? '99+' : count}</span>}
                    </span>
                    <span className={label}>{item.label}</span>
                  </Link>
                )
              })}
            </div>
          )
        })}
      </nav>

      <div className="shrink-0 space-y-1 border-t border-[color:var(--color-border)] px-2.5 py-2.5">
        <button type="button" onClick={onLauncher} title={tip('All spaces')} style={{ '--hue': 'var(--orion-accent)' } as React.CSSProperties} className={row} aria-label="All spaces">
          <span className={chip}>
            <LayoutGrid className="h-5 w-5" />
          </span>
          <span className={label}>All spaces</span>
        </button>
        <button type="button" onClick={onRaiseRequest} title={tip('Raise a request')} style={{ '--hue': 'var(--lumen-slate)' } as React.CSSProperties} className={row} aria-label="Raise a request">
          <span className={chip}>
            <LifeBuoy className="h-5 w-5" />
          </span>
          <span className={label}>Raise a request</span>
        </button>
        <button type="button" onClick={toggle} aria-expanded={open} title={open ? undefined : 'Open the sidebar'} style={{ '--hue': 'var(--lumen-slate)' } as React.CSSProperties} className={row} aria-label={open ? 'Fold the sidebar' : 'Open the sidebar'}>
          <span className={chip}>{open ? <PanelLeftClose className="h-5 w-5" /> : <PanelLeftOpen className="h-5 w-5" />}</span>
          <span className={label}>Fold sidebar</span>
        </button>
      </div>
    </aside>
  )
}
