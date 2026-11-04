import { useEffect, useRef } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import type { DashboardTab } from '../../dashboards/registry'

/**
 * The views inside one dashboard. The current filters travel with every link, so switching view keeps the
 * selection. On a narrow screen the strip scrolls sideways and the current view scrolls into sight.
 *
 * Only the strip itself is scrolled, and only when the view changes. (It used to call `scrollIntoView` from a ref on
 * every render, which also scrolled the whole page back up to the tabs whenever anything on the dashboard re-rendered:
 * switching the comparison, for one.)
 */
export function ViewTabs({
  tabs,
  base,
  search,
  label,
}: {
  tabs: DashboardTab[]
  /** Route the tabs hang off, e.g. /dashboard/orion. */
  base: string
  search: string
  label: string
}) {
  const strip = useRef<HTMLElement>(null)
  const { pathname } = useLocation()

  useEffect(() => {
    const nav = strip.current
    const current = nav?.querySelector<HTMLElement>('[aria-current="page"]')
    if (!nav || !current) return
    const box = nav.getBoundingClientRect()
    const tab = current.getBoundingClientRect()
    const margin = 16
    if (tab.left < box.left) nav.scrollLeft -= box.left - tab.left + margin
    else if (tab.right > box.right) nav.scrollLeft += tab.right - box.right + margin
  }, [pathname])

  return (
    <nav ref={strip} aria-label={label} className="scroll-quiet -mx-4 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
      <div className="lumen-viewtabs flex w-max min-w-full gap-1 rounded-xl bg-muted p-1 sm:w-fit sm:min-w-0">
        {tabs.map((item) => {
          const Icon = item.icon
          return (
            <NavLink
              key={item.view}
              end={item.path === ''}
              to={{ pathname: item.path ? `${base}/${item.path}` : base, search }}
              className={({ isActive }) =>
                `interactive relative flex shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium ${
                  isActive
                    ? 'bg-surface text-[color:var(--color-text)] shadow-card'
                    : 'text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <Icon
                    className={`h-4 w-4 ${isActive ? 'text-accent' : 'text-[color:var(--color-text-faint)]'}`}
                    aria-hidden="true"
                  />
                  {item.label}
                </>
              )}
            </NavLink>
          )
        })}
      </div>
    </nav>
  )
}
