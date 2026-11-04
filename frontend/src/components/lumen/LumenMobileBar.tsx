import { Link, useLocation } from 'react-router-dom'
import { House, LayoutGrid, ListChecks, MessagesSquare, Search } from 'lucide-react'
import { useAssistant } from '../../ai/AssistantContext'
import { useTabMemory } from '../../context/TabMemoryContext'
import { useTasks } from '../../context/TasksContext'

/** The phone's navigation: a floating bar of the five things most people reach for, with search in the middle and the whole grid of spaces on the right. */
export function LumenMobileBar({ unread, onLauncher }: { unread: number; onLauncher: () => void }) {
  const { pathname } = useLocation()
  const last = useTabMemory()
  const { me } = useTasks()
  const { setPaletteOpen } = useAssistant()
  const tab = (to: string, label: string, icon: typeof House, active: boolean, count = 0) => {
    const Icon = icon
    return (
      <Link key={label} to={to} aria-label={label} aria-current={active ? 'page' : undefined} className={`interactive relative grid h-12 w-12 place-items-center rounded-full ${active ? 'bg-accent-dim text-accent' : 'text-[color:var(--color-text-muted)]'}`}>
        <Icon className="h-5 w-5" />
        {count > 0 && <span className="absolute right-1 top-1 h-2.5 w-2.5 rounded-full bg-amber ring-2 ring-[color:var(--color-surface)]" />}
      </Link>
    )
  }
  return (
    <nav aria-label="Main" className="fixed inset-x-4 bottom-[max(0.75rem,env(safe-area-inset-bottom))] z-40 mx-auto flex max-w-sm items-center justify-between rounded-full border border-[color:var(--color-border)] bg-[color:var(--orion-surface-fill)] px-2 py-1.5 shadow-overlay backdrop-blur-xl lg:hidden">
      {tab('/', 'Today', House, pathname === '/')}
      {tab(last.tasks, 'Tasks', ListChecks, pathname.startsWith('/tasks'), me.unread + me.attention)}
      <button type="button" onClick={() => setPaletteOpen(true)} aria-label="Search" className="btn-primary interactive -mt-6 grid h-14 w-14 place-items-center rounded-full">
        <Search className="h-6 w-6" />
      </button>
      {tab(last.messages, 'Messages', MessagesSquare, pathname.startsWith('/messages'), unread)}
      <button type="button" onClick={onLauncher} aria-label="All spaces" className="interactive grid h-12 w-12 place-items-center rounded-full text-[color:var(--color-text-muted)]">
        <LayoutGrid className="h-5 w-5" />
      </button>
    </nav>
  )
}
