import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { CalendarPlus, ChevronDown, FileText, FolderUp, LayoutTemplate, LifeBuoy, ListPlus, LogOut, Plus, ReceiptText, Search, Settings, Sparkles } from 'lucide-react'
import { useAssistant } from '../../ai/AssistantContext'
import { AssistantButton } from '../assistant/Launcher'
import { AppearanceMenu } from '../appearance/AppearanceMenu'
import { FollowupsBell } from '../followups/FollowupsBell'
import { RefreshButton } from '../RefreshButton'
import { TasksBell } from '../tasks/TasksBell'
import { Tooltip } from '../ui/Tooltip'
import { UserAvatar } from '../UserAvatar'
import { useAppearance } from '../../context/AppearanceContext'
import { useAuth } from '../../context/AuthContext'
import { usePresence } from '../../hooks/usePresence'
import type { User } from '../../types'
import { pageTitle, roleLabel } from '../nav/navigation'

/** Closes a floating menu when the pointer goes down elsewhere or Escape is pressed. */
function useDismiss(open: boolean, close: () => void) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onPointer = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) close()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, close])
  return box
}

type Create = { label: string; hint: string; to?: string; run?: () => void; icon: typeof Plus; hue: string; visible: boolean }

/** "+": start something new from anywhere. Only what this person is allowed to start is listed. */
function QuickCreate({ user, onRaiseRequest }: { user: User; onRaiseRequest: () => void }) {
  const [open, setOpen] = useState(false)
  const { present, leaving } = usePresence(open)
  const box = useDismiss(open, () => setOpen(false))
  const assistant = useAssistant()
  const items: Create[] = [
    { label: 'New task', hint: 'Give work to someone', to: '/tasks/mine?new=1', icon: ListPlus, hue: 'indigo', visible: true },
    { label: 'New bill', hint: 'Raise a tax invoice', to: '/utility/billing/new', icon: ReceiptText, hue: 'coral', visible: user.pages.includes('utility') },
    { label: 'New letter', hint: 'Write on the letterhead', to: '/letterhead/letters/new', icon: FileText, hue: 'amber', visible: user.pages.includes('letterhead') },
    { label: 'Upload a document', hint: 'File a paper', to: '/documents', icon: FolderUp, hue: 'orange', visible: user.pages.includes('documents') },
    { label: 'New attendance register', hint: 'A case and a month', to: '/attendance/new', icon: CalendarPlus, hue: 'cyan', visible: user.pages.includes('attendance') },
    { label: 'Ask the Copilot', hint: 'Questions, drafts, reports', run: () => assistant.setOpen(true), icon: Sparkles, hue: 'violet', visible: assistant.enabled },
    { label: 'Raise a request', hint: 'Tell us what you need', run: onRaiseRequest, icon: LifeBuoy, hue: 'slate', visible: true },
  ].filter((item) => item.visible)

  return (
    <div ref={box} className="relative">
      <Tooltip label="Create">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label="Create"
          className="btn-primary interactive grid h-10 w-10 place-items-center rounded-full"
        >
          <Plus className={`h-5 w-5 transition-transform duration-300 ${open ? 'rotate-45' : ''}`} />
        </button>
      </Tooltip>
      {present && (
        <div role="menu" aria-label="Create" className={`${leaving ? 'pop-out' : 'pop-in'} overlay absolute right-0 top-full z-50 mt-3 w-72 rounded-3xl border border-[color:var(--color-border)] p-2`}>
          <p className="eyebrow px-3 pb-1 pt-2">Create</p>
          {items.map((item) => {
            const Icon = item.icon
            const body = (
              <>
                <span className="lumen-chip grid h-9 w-9 shrink-0 place-items-center rounded-xl">
                  <Icon className="h-[18px] w-[18px]" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-[color:var(--color-text)]">{item.label}</span>
                  <span className="t-caption block truncate">{item.hint}</span>
                </span>
              </>
            )
            const cls = 'lumen-dock-item interactive flex w-full items-center gap-3 rounded-2xl px-2 py-1.5 text-left hover:bg-muted'
            const style = { '--hue': `var(--lumen-${item.hue})` } as React.CSSProperties
            return item.to ? (
              <Link key={item.label} to={item.to} role="menuitem" style={style} className={cls} onClick={() => setOpen(false)}>
                {body}
              </Link>
            ) : (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                style={style}
                className={cls}
                onClick={() => {
                  setOpen(false)
                  item.run?.()
                }}
              >
                {body}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

function UserMenu({ user, onRaiseRequest }: { user: User; onRaiseRequest: () => void }) {
  const { logout } = useAuth()
  const { setExperience } = useAppearance()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const { present, leaving } = usePresence(open)
  const box = useDismiss(open, () => setOpen(false))
  const item = 'interactive flex w-full items-center gap-3 rounded-2xl px-3 py-2 text-left text-sm text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]'
  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="interactive flex items-center gap-2 rounded-full border border-[color:var(--color-border)] bg-[color:var(--orion-surface-fill)] py-1 pl-1 pr-1.5 hover:border-[color:var(--color-border-strong)] sm:pr-3"
      >
        <UserAvatar user={user} size="sm" />
        <span className="hidden max-w-[9rem] truncate text-sm font-semibold sm:inline">{user.display_name}</span>
        <ChevronDown className={`hidden h-3.5 w-3.5 text-[color:var(--color-text-faint)] transition sm:block ${open ? 'rotate-180' : ''}`} />
      </button>
      {present && (
        <div role="menu" className={`${leaving ? 'pop-out' : 'pop-in'} overlay absolute right-0 top-full z-50 mt-3 w-64 rounded-3xl border border-[color:var(--color-border)] p-2`}>
          <div className="mb-1 flex items-center gap-3 rounded-2xl bg-accent-dim px-3 py-3">
            <UserAvatar user={user} size="md" />
            <div className="min-w-0">
              <p className="font-display truncate text-sm font-semibold text-[color:var(--color-text)]">{user.display_name}</p>
              <p className="text-xs text-[color:var(--color-text-muted)]">{roleLabel[user.role] || user.role}</p>
            </div>
          </div>
          <NavLink to="/settings" role="menuitem" onClick={() => setOpen(false)} className={item}>
            <Settings className="h-4 w-4" /> Settings
          </NavLink>
          <button type="button" role="menuitem" onClick={() => { setOpen(false); onRaiseRequest() }} className={item}>
            <LifeBuoy className="h-4 w-4" /> Raise a request
          </button>
          <button type="button" role="menuitem" onClick={() => { setOpen(false); setExperience('classic') }} className={item}>
            <LayoutTemplate className="h-4 w-4" /> Switch to the classic look
          </button>
          <div className="my-1 border-t border-[color:var(--color-border)]" />
          <button
            type="button"
            role="menuitem"
            onClick={async () => {
              setOpen(false)
              await logout()
              navigate('/')
            }}
            className="interactive flex w-full items-center gap-3 rounded-2xl px-3 py-2 text-left text-sm text-negative hover:bg-negative-dim"
          >
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * The top of the Lumen interface: where you are, a search that jumps anywhere or asks the Copilot, "+" to start something, and the bells and menus.
 * The title is large and friendly; on the Today page it is replaced by that page's own greeting.
 */
export function LumenTopBar({ user, children, onRaiseRequest }: { user: User; children?: ReactNode; onRaiseRequest: () => void }) {
  const location = useLocation()
  const { setPaletteOpen } = useAssistant()
  const here = pageTitle(location.pathname)
  const isHome = location.pathname === '/'
  const mac = typeof navigator !== 'undefined' && /mac/i.test(navigator.platform)

  return (
    <header className="relative z-40 shrink-0 pt-[env(safe-area-inset-top)]">
      <div className="flex items-center gap-3 px-4 py-3 sm:px-6 lg:px-8">
        <div className="min-w-0 flex-1 md:flex-none md:w-40 xl:w-56">
          <p className="truncate text-sm font-semibold leading-none">
            {isHome ? (
              <span className="text-[color:var(--color-text)]">Today</span>
            ) : (
              <>
                <span className="text-[color:var(--color-text-faint)]">{here.section}</span>
                <span className="mx-1.5 text-[color:var(--color-text-faint)]" aria-hidden="true">/</span>
                <span className="text-[color:var(--color-text)]">{here.title}</span>
              </>
            )}
          </p>
        </div>

        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          aria-label="Search, jump to a page or ask the Copilot"
          className="interactive mx-auto hidden h-11 min-w-0 max-w-xl flex-1 items-center gap-3 rounded-full border border-[color:var(--color-border)] bg-[color:var(--orion-surface-fill)] px-4 text-left text-sm text-[color:var(--color-text-faint)] shadow-card backdrop-blur-xl hover:border-[color:var(--color-border-strong)] hover:shadow-raised md:flex"
        >
          <Search className="h-4 w-4" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate">Search, jump anywhere or ask the Copilot…</span>
          <kbd className="rounded-md border border-[color:var(--color-border)] bg-muted px-1.5 py-0.5 text-[10px] font-semibold text-[color:var(--color-text-muted)]">{mac ? '⌘' : 'Ctrl'} K</kbd>
        </button>

        <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:gap-2">
          <button type="button" onClick={() => setPaletteOpen(true)} aria-label="Search" className="interactive grid h-10 w-10 place-items-center rounded-full text-[color:var(--color-text-muted)] hover:bg-muted md:hidden">
            <Search className="h-5 w-5" />
          </button>
          <QuickCreate user={user} onRaiseRequest={onRaiseRequest} />
          <span className="hidden xl:contents">
            <RefreshButton compact />
          </span>
          <TasksBell />
          <FollowupsBell />
          <AssistantButton />
          <AppearanceMenu />
          <UserMenu user={user} onRaiseRequest={onRaiseRequest} />
        </div>
      </div>
      {children}
    </header>
  )
}
