import { NavLink, Outlet } from 'react-router-dom'
import { FileUp, LayoutTemplate, ScrollText } from 'lucide-react'

const TABS = [
  { to: '/letterhead/letters', label: 'Letters', icon: ScrollText },
  { to: '/letterhead/pdf', label: 'Put a PDF on the letterhead', icon: FileUp },
  { to: '/letterhead/design', label: 'Header and footer', icon: LayoutTemplate },
]

/** Anything that goes out on the company letterhead: letters typed here, and PDFs made elsewhere. */
export function LetterheadPage() {
  return (
    <div className="mx-auto w-full max-w-[1500px] space-y-4">
      <nav aria-label="Letterhead">
        <div className="scroll-quiet flex w-max max-w-full gap-1 overflow-x-auto rounded-xl bg-muted p-1">
          {TABS.map((tab) => {
            const Icon = tab.icon
            return (
              <NavLink
                key={tab.to}
                to={tab.to}
                className={({ isActive }) =>
                  `flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:ring-2 focus-visible:ring-accent ${
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
      <Outlet />
    </div>
  )
}
