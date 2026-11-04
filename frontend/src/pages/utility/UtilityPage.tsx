import { NavLink, Outlet } from 'react-router-dom'
import { CalendarClock, FileMinus2, HandCoins, Hourglass, Landmark, Percent, Receipt } from 'lucide-react'

const TABS = [
  { to: '/utility/billing', label: 'Billing', icon: Receipt },
  { to: '/utility/receivables', label: 'Outstanding', icon: Hourglass },
  { to: '/utility/credit-notes', label: 'Credit notes', icon: FileMinus2 },
  { to: '/utility/tds', label: 'TDS', icon: Percent },
  { to: '/utility/gst', label: 'GST', icon: Landmark },
  { to: '/utility/statutory', label: 'EPFO and ESIC', icon: HandCoins },
  { to: '/utility/due', label: 'Monthly billing', icon: CalendarClock },
]

/** Everyday tools that act on the books rather than report on them: billing, what is still owed, repeat bills. */
export function UtilityPage() {
  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-4">
      {/* The rail already names the tool. The strip only appears once there is a second one. */}
      {TABS.length > 1 && (
        <nav aria-label="Utilities">
          <div className="flex w-max gap-1 rounded-xl bg-muted p-1">
            {TABS.map((tab) => {
              const Icon = tab.icon
              return (
                <NavLink
                  key={tab.to}
                  to={tab.to}
                  className={({ isActive }) =>
                    `flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-accent ${
                      isActive
                        ? 'bg-surface text-[color:var(--color-text)] shadow-sm'
                        : 'text-[color:var(--color-text-muted)] hover:bg-surface/60 hover:text-[color:var(--color-text)]'
                    }`
                  }
                >
                  <Icon className="h-4 w-4 text-accent" aria-hidden="true" />
                  {tab.label}
                </NavLink>
              )
            })}
          </div>
        </nav>
      )}
      <Outlet />
    </div>
  )
}
