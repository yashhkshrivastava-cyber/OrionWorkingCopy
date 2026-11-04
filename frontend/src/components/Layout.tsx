import { lazy, Suspense, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { usePresence } from '../hooks/usePresence'
import { NavLink, Outlet, useNavigate, useLocation, Link } from 'react-router-dom'
import {
  ChevronDown,
  House,
  LifeBuoy,
  LogIn,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Sparkles,
  X,
} from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { ChatProvider, messagePreview, useChat } from '../context/ChatContext'
import { TabMemoryProvider, areaOf, useTabMemory, type NavArea } from '../context/TabMemoryContext'
import { DataRefreshProvider } from '../context/DataRefreshContext'
import { FollowupsProvider } from '../context/FollowupsContext'
import { FollowupsBell } from './followups/FollowupsBell'
import { TasksProvider, useTasks } from '../context/TasksContext'
import { NAV_GROUPS, pageTitle, roleLabel } from './nav/navigation'
import { useAppearance } from '../context/AppearanceContext'
import { useLumenPointer } from '../lumen/useLumenPointer'
import { TasksBell } from './tasks/TasksBell'
import { AppearanceMenu } from './appearance/AppearanceMenu'
import { RefreshButton } from './RefreshButton'
import { UserAvatar } from './UserAvatar'
import { WorkspacePanes, isWorkspacePath } from './WorkspacePanes'
import { BrandMark } from './BrandMark'
import { RaiseRequestModal } from './RaiseRequestModal'
import { AssistantProvider } from '../ai/AssistantContext'
import { AssistantPanel } from './assistant/AssistantPanel'
import { AssistantButton, FloatingLauncher } from './assistant/Launcher'
import { CommandPalette, type Destination } from './assistant/CommandPalette'
import type { User } from '../types'

function railItemClass(active: boolean, collapsed: boolean) {
  return `interactive group relative flex items-center gap-3 rounded-lg text-[13px] font-medium ${
    collapsed ? 'h-10 w-10 justify-center' : 'px-3 py-2'
  } ${
    active
      ? 'bg-rail-active text-rail-strong'
      : 'text-[color:var(--color-rail-text)] hover:bg-rail-hover hover:text-rail-strong'
  }`
}

function Count({ value, collapsed }: { value: number; collapsed: boolean }) {
  if (value <= 0) return null
  if (collapsed) {
    return <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-amber ring-2 ring-[color:var(--color-rail)]" />
  }
  return (
    <span className="ml-auto rounded-full bg-amber px-1.5 py-0.5 text-[10px] font-bold leading-none text-ink">
      {value > 99 ? '99+' : value}
    </span>
  )
}

function Rail({
  user,
  unread,
  collapsed,
  onNavigate,
  onRaiseRequest,
}: {
  user: User
  unread: number
  collapsed: boolean
  onNavigate?: () => void
  onRaiseRequest: () => void
}) {
  const location = useLocation()
  const last = useTabMemory()
  const current = areaOf(location.pathname)
  const { me } = useTasks()
  const counts: Partial<Record<NavArea, number>> = { messages: unread, tasks: me.unread + me.attention, admin: user.pending_signups ?? 0 }

  return (
    <nav aria-label="Main" className={`scroll-quiet flex-1 overflow-y-auto ${collapsed ? 'px-2 py-3' : 'px-3 py-4'}`}>
      <NavLink
        to="/"
        end
        onClick={onNavigate}
        title={collapsed ? 'Home' : undefined}
        className={({ isActive }) => railItemClass(isActive, collapsed)}
      >
        {({ isActive }) => (
          <>
            {isActive && (
              <span
                className={`absolute h-5 w-1 rounded-r bg-rail-accent shadow-[var(--orion-glow)] ${collapsed ? '-left-2' : '-left-3'}`}
                aria-hidden="true"
              />
            )}
            <House className={`h-[18px] w-[18px] shrink-0 ${isActive ? 'text-rail-accent' : ''}`} />
            {!collapsed && 'Home'}
          </>
        )}
      </NavLink>

      {NAV_GROUPS.map((group) => {
        const items = group.items.filter((item) => item.visible(user))
        if (!items.length) return null
        return (
          <div key={group.label} className={collapsed ? 'mt-3 border-t border-[color:var(--color-rail-border)] pt-3' : 'mt-5'}>
            {!collapsed && (
              <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--color-rail-text-faint)]">
                {group.label}
              </p>
            )}
            <div className="space-y-0.5">
              {items.map((item) => {
                const Icon = item.icon
                const active = current === item.area
                return (
                  <Link
                    key={item.area}
                    to={last[item.area]}
                    onClick={onNavigate}
                    title={collapsed ? item.label : undefined}
                    aria-current={active ? 'page' : undefined}
                    className={railItemClass(active, collapsed)}
                  >
                    {active && (
                      <span
                        className={`absolute h-5 w-1 rounded-r bg-rail-accent shadow-[var(--orion-glow)] ${collapsed ? '-left-2' : '-left-3'}`}
                        aria-hidden="true"
                      />
                    )}
                    <Icon className={`h-[18px] w-[18px] shrink-0 ${active ? 'text-rail-accent' : ''}`} />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                    <Count value={counts[item.area] ?? 0} collapsed={collapsed} />
                  </Link>
                )
              })}
            </div>
          </div>
        )
      })}

      <div className={collapsed ? 'mt-3 border-t border-[color:var(--color-rail-border)] pt-3' : 'mt-5'}>
        {!collapsed && (
          <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-[color:var(--color-rail-text-faint)]">
            Support
          </p>
        )}
        <button
          type="button"
          onClick={() => {
            onNavigate?.()
            onRaiseRequest()
          }}
          title={collapsed ? 'Raise a request' : undefined}
          className={`w-full ${railItemClass(false, collapsed)}`}
        >
          <LifeBuoy className="h-[18px] w-[18px] shrink-0" />
          {!collapsed && 'Raise a request'}
        </button>
      </div>
    </nav>
  )
}

function Brand({ collapsed }: { collapsed: boolean }) {
  return (
    <Link to="/" className={`flex h-16 shrink-0 items-center gap-3 ${collapsed ? 'justify-center' : 'px-5'}`}>
      <BrandMark size={30} />
      {!collapsed && (
        <span className="min-w-0 leading-tight">
          <span className="font-display block truncate text-[15px] font-bold text-rail-strong">Prakash Securities</span>
          <span className="block text-[11px] text-[color:var(--color-rail-text-faint)]">Orion workspace</span>
        </span>
      )}
    </Link>
  )
}

// Calls are a separate download too: most visits never make or take one, and it is fetched once someone is signed in.
const CallHost = lazy(() => import('./calls/CallHost'))
// the first-visit welcome, also fetched only for someone signed in
const WelcomeTour = lazy(() => import('./welcome/WelcomeTour'))

function Calls() {
  const { user } = useAuth()
  return user ? (
    <Suspense fallback={null}>
      <CallHost />
      <WelcomeTour />
    </Suspense>
  ) : null
}

export function Layout() {
  return (
    <DataRefreshProvider>
      <ChatProvider>
        <Calls />
        <TabMemoryProvider>
          <AssistantProvider>
            <FollowupsProvider>
              <TasksProvider>
                <LayoutShell />
              </TasksProvider>
            </FollowupsProvider>
          </AssistantProvider>
        </TabMemoryProvider>
      </ChatProvider>
    </DataRefreshProvider>
  )
}

// Lumen's frame is a separate download, fetched the first time someone uses that interface.
const LumenFrame = lazy(() => import('./lumen/LumenFrame'))
// where the sidebar's state is kept is next to the sidebar, but reading it must not pull the sidebar into the start-up download
const readDockOpen = (): boolean => {
  try {
    return localStorage.getItem('orion-lumen-dock-open') !== '0'
  } catch {
    return true
  }
}
const RAIL_KEY = 'orion-rail-collapsed'

function LayoutShell() {
  const { user, logout } = useAuth()
  const { unread, incoming, clearIncoming } = useChat()
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [userOpen, setUserOpen] = useState(false)
  const [requestOpen, setRequestOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(RAIL_KEY) === '1'
    } catch {
      return false
    }
  })
  const { prefs, setExperience } = useAppearance()
  const lumen = prefs.experience === 'lumen' && Boolean(user)
  const [dockOpen, setDockOpen] = useState(readDockOpen)
  const [launcherOpen, setLauncherOpen] = useState(false)
  useLumenPointer(lumen)
  const userMenu = useRef<HTMLDivElement>(null)
  const userMenuPresence = usePresence(userOpen)
  const navPresence = usePresence(menuOpen)

  const toggleRail = () =>
    setCollapsed((value) => {
      try {
        localStorage.setItem(RAIL_KEY, value ? '0' : '1')
      } catch {
        /* the rail still toggles for this visit */
      }
      return !value
    })

  // Charts measure their container; tell them the workspace changed width.
  useEffect(() => {
    const timer = window.setTimeout(() => window.dispatchEvent(new Event('resize')), 220)
    return () => window.clearTimeout(timer)
  }, [collapsed])

  const handleLogout = async () => {
    setMenuOpen(false)
    setUserOpen(false)
    await logout()
    navigate('/')
  }

  const isDashboard = location.pathname.startsWith('/dashboard')
  const isMessages = location.pathname.startsWith('/messages')
  const isHome = location.pathname === '/'
  const isWorkspace = isWorkspacePath(location.pathname)
  const mainRef = useRef<HTMLElement>(null)
  const sectionScroll = useRef({ dashboard: 0, data: 0, admin: 0, messages: 0, other: 0 })
  const section = isDashboard
    ? 'dashboard'
    : location.pathname.startsWith('/data')
      ? 'data'
      : location.pathname.startsWith('/admin')
        ? 'admin'
        : isMessages
          ? 'messages'
          : 'other'

  useLayoutEffect(() => {
    const main = mainRef.current
    if (!main) return
    const positions = sectionScroll.current // a plain object that lives as long as the shell: the same one when the cleanup runs
    main.scrollTop = positions[section]
    return () => {
      positions[section] = main.scrollTop
    }
  }, [section])

  useEffect(() => {
    setMenuOpen(false)
    setUserOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!incoming) return
    if (location.pathname === `/messages/${incoming.message.chat_id}`) {
      clearIncoming()
      return
    }
    const timer = window.setTimeout(clearIncoming, 7000)
    return () => window.clearTimeout(timer)
  }, [incoming, location.pathname, clearIncoming])

  useEffect(() => {
    if (!menuOpen) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.body.style.overflow = previous
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  useEffect(() => {
    if (!userOpen) return
    const onPointer = (event: PointerEvent) => {
      if (!userMenu.current?.contains(event.target as Node)) setUserOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setUserOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [userOpen])

  const here = pageTitle(location.pathname)

  // Where the command palette can jump to: the same pages the navigation rail shows this person.
  const last = useTabMemory()
  const destinations: Destination[] = user
    ? [
        { label: 'Home', to: '/', icon: House, group: 'Go to' },
        ...NAV_GROUPS.flatMap((group) => group.items.filter((item) => item.visible(user))).map((item) => ({ label: item.label, to: last[item.area], icon: item.icon, group: 'Go to' })),
        { label: 'Settings', to: '/settings', icon: Settings, group: 'Go to' },
      ]
    : []

  const mainArea = (
    <main
      ref={mainRef}
      className={`relative min-h-0 flex-1 ${isMessages ? 'overflow-hidden' : 'overflow-auto'}`}
    >
      {!isHome && !isMessages && (
        <div className="canvas-grid pointer-events-none absolute inset-x-0 top-0 h-[340px]" aria-hidden="true" />
      )}
      <div className={`relative ${isMessages ? 'h-full' : ''}`}>
        <WorkspacePanes />
        {!isWorkspace && (
          <div
            key={'/' + (location.pathname.split('/').filter(Boolean)[0] || '')}
            className={`page-enter ${
              isHome ? 'w-full px-0 py-0' : 'mx-auto w-full max-w-5xl px-4 py-5 sm:px-6 sm:py-6 lg:px-8'
            } ${isHome ? '' : 'pb-[max(1rem,env(safe-area-inset-bottom))]'}`}
          >
            <Outlet />
          </div>
        )}
      </div>
    </main>
  )

  const overlays = (
    <>
      {user && <AssistantPanel />}

      {user && navPresence.present && (
        <div className="fixed inset-0 z-[70] lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className={`${navPresence.leaving ? 'backdrop-out' : 'backdrop-in'} absolute inset-0 bg-scrim backdrop-blur-[2px]`}
            onClick={() => setMenuOpen(false)}
          />
          <aside className={`${navPresence.leaving ? 'drawer-left-out' : 'drawer-in'} relative flex h-full w-[17rem] max-w-[85vw] flex-col bg-rail pt-[env(safe-area-inset-top)] shadow-overlay`}>
            <div className="flex items-center justify-between pr-3">
              <Brand collapsed={false} />
              <button
                type="button"
                onClick={() => setMenuOpen(false)}
                aria-label="Close navigation"
                className="interactive rounded-lg p-2 text-[color:var(--color-rail-text)] hover:bg-rail-active hover:text-rail-strong"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <Rail
              user={user}
              unread={unread}
              collapsed={false}
              onNavigate={() => setMenuOpen(false)}
              onRaiseRequest={() => setRequestOpen(true)}
            />
          </aside>
        </div>
      )}

      {incoming && location.pathname !== `/messages/${incoming.message.chat_id}` && (
        <Link
          to={`/messages/${incoming.message.chat_id}`}
          onClick={clearIncoming}
          className="toast-in overlay fixed bottom-[max(1rem,env(safe-area-inset-bottom))] right-4 z-40 max-w-xs rounded-xl border border-[color:var(--color-border)] px-4 py-3"
        >
          <p className="text-xs font-semibold text-accent">New message</p>
          <p className="truncate text-sm font-medium">{incoming.senderName}</p>
          <p className="mt-0.5 truncate text-xs text-[color:var(--color-text-muted)]">{messagePreview(incoming.message)}</p>
        </Link>
      )}
      {user && <RaiseRequestModal open={requestOpen} onClose={() => setRequestOpen(false)} />}
      {user && !isMessages && !lumen && <FloatingLauncher />}
      {user && <CommandPalette destinations={destinations} />}
    </>
  )

  if (lumen && user) {
    return (
      <Suspense fallback={<div className="app-canvas h-dvh" aria-busy="true" />}>
        <LumenFrame
          user={user}
          unread={unread}
          dockOpen={dockOpen}
          onDockOpen={setDockOpen}
          launcherOpen={launcherOpen}
          setLauncherOpen={setLauncherOpen}
          onRaiseRequest={() => setRequestOpen(true)}
          overlays={overlays}
        >
          {mainArea}
        </LumenFrame>
      </Suspense>
    )
  }

  return (
    <div className="app-canvas flex h-dvh overflow-hidden">
      {user && (
        <aside
          className={`relative z-30 hidden shrink-0 flex-col border-r border-[color:var(--color-rail-border)] bg-rail transition-[width] duration-[var(--orion-dur-base)] ease-[var(--orion-ease)] lg:flex ${
            collapsed ? 'w-[60px]' : 'w-60'
          }`}
        >
          <Brand collapsed={collapsed} />
          <Rail user={user} unread={unread} collapsed={collapsed} onRaiseRequest={() => setRequestOpen(true)} />
          <div className={`border-t border-[color:var(--color-rail-border)] ${collapsed ? 'p-2' : 'p-3'}`}>
            <button
              type="button"
              onClick={toggleRail}
              aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
              title={collapsed ? 'Expand navigation' : undefined}
              className={`w-full ${railItemClass(false, collapsed)}`}
            >
              {collapsed ? (
                <PanelLeftOpen className="h-[18px] w-[18px] shrink-0" />
              ) : (
                <>
                  <PanelLeftClose className="h-[18px] w-[18px] shrink-0" />
                  Collapse
                </>
              )}
            </button>
          </div>
        </aside>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="relative z-40 shrink-0 border-b border-[color:var(--color-border)] bg-surface/85 pt-[env(safe-area-inset-top)] backdrop-blur-md">
          <div className="flex h-14 items-center gap-3 px-3 sm:px-5 lg:px-6">
            {user ? (
              <button
                type="button"
                onClick={() => setMenuOpen(true)}
                className="relative -ml-1 rounded-lg p-2 text-[color:var(--color-text)] hover:bg-muted lg:hidden"
                aria-label="Open navigation"
              >
                <Menu className="h-5 w-5" />
                {unread > 0 && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-amber" />}
              </button>
            ) : null}

            {user ? (
              <div className="min-w-0">
                <p className="eyebrow leading-none">{here.section}</p>
                <p className="t-h3 mt-1 truncate leading-none text-[color:var(--color-text)]">
                  {here.title}
                </p>
              </div>
            ) : (
              <Link to="/" className="flex items-center gap-2.5">
                <BrandMark size={28} />
                <span className="font-display text-[15px] font-bold tracking-tight">Prakash Securities</span>
              </Link>
            )}

            <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
              {user && <RefreshButton compact />}
              {user && <TasksBell />}
              {user && <FollowupsBell />}
              {user && <AssistantButton />}
              {user && (
                <button
                  type="button"
                  onClick={() => setExperience('lumen')}
                  title="Try Lumen, the new look of Orion. You can come back here any time."
                  className="interactive hidden h-9 items-center gap-1.5 rounded-full border border-[color:var(--color-border)] bg-surface px-3 text-xs font-semibold text-[color:var(--color-text)] hover:border-[color:var(--color-border-strong)] md:inline-flex"
                >
                  <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
                  Try the new look
                </button>
              )}
              <AppearanceMenu />
              {!user && (
                <Link
                  to="/login"
                  className="btn-primary interactive inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-semibold"
                >
                  <LogIn className="h-4 w-4" />
                  Sign in
                </Link>
              )}
              {user && (
                <div ref={userMenu} className="relative">
                  <button
                    type="button"
                    onClick={() => setUserOpen((open) => !open)}
                    aria-haspopup="menu"
                    aria-expanded={userOpen}
                    className="flex items-center gap-2 rounded-full border border-[color:var(--color-border)] bg-surface py-1 pl-1 pr-1.5 hover:border-[color:var(--color-border-strong)] sm:pr-2.5"
                  >
                    <UserAvatar user={user} size="sm" />
                    <span className="hidden max-w-[9rem] truncate text-sm font-medium sm:inline">{user.display_name}</span>
                    <ChevronDown
                      className={`hidden h-3.5 w-3.5 text-[color:var(--color-text-faint)] transition sm:block ${userOpen ? 'rotate-180' : ''}`}
                    />
                  </button>
                  {userMenuPresence.present && (
                    <div
                      role="menu"
                      className={`${userMenuPresence.leaving ? 'pop-out' : 'pop-in'} overlay absolute right-0 top-full z-50 mt-2 w-60 rounded-xl border border-[color:var(--color-border)] p-1.5`}
                    >
                      <div className="mb-1 flex items-center gap-3 rounded-lg bg-muted/70 px-3 py-2.5">
                        <UserAvatar user={user} size="sm" />
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold">{user.display_name}</p>
                          <p className="text-xs text-[color:var(--color-text-muted)]">{roleLabel[user.role] || user.role}</p>
                        </div>
                      </div>
                      <NavLink
                        to="/settings"
                        role="menuitem"
                        onClick={() => setUserOpen(false)}
                        className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]"
                      >
                        <Settings className="h-4 w-4" />
                        Settings
                      </NavLink>
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setUserOpen(false)
                          setRequestOpen(true)
                        }}
                        className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]"
                      >
                        <LifeBuoy className="h-4 w-4" />
                        Raise a request
                      </button>
                      <div className="my-1 border-t border-[color:var(--color-border)]" />
                      <button
                        type="button"
                        role="menuitem"
                        onClick={handleLogout}
                        className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-negative hover:bg-negative-dim"
                      >
                        <LogOut className="h-4 w-4" />
                        Sign out
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </header>

        {mainArea}
      </div>

      {overlays}
    </div>
  )
}
