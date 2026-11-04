import { useLayoutEffect, useState, type ReactNode } from 'react'
import { type Location, Routes, useLocation } from 'react-router-dom'
import {
  adminRouteTree,
  attendanceRouteTree,
  bankRouteTree,
  dashboardRouteTree,
  dataRouteTree,
  documentsRouteTree,
  etlRouteTree,
  letterheadRouteTree,
  messagesRouteTree,
  pdfToolsRouteTree,
  tasksRouteTree,
  sqlRouteTree,
  tendersRouteTree,
  utilityRouteTree,
} from '../workspaceRoutes'

type SectionId = 'dashboard' | 'data' | 'utility' | 'letterhead' | 'pdf' | 'documents' | 'bank' | 'tenders' | 'attendance' | 'etl' | 'sql' | 'admin' | 'messages' | 'tasks'

const PANE_CLASS: Record<SectionId, string> = {
  dashboard: 'mx-auto w-full max-w-[1680px] px-4 py-5 sm:px-6 lg:px-8 pb-[max(1rem,env(safe-area-inset-bottom))]',
  data: 'w-full px-3 py-3 sm:px-4 lg:px-6 pb-[max(0.75rem,env(safe-area-inset-bottom))]',
  utility: 'w-full px-4 py-5 sm:px-6 lg:px-8 pb-[max(1rem,env(safe-area-inset-bottom))]',
  letterhead: 'w-full px-4 py-5 sm:px-6 lg:px-8 pb-[max(1rem,env(safe-area-inset-bottom))]',
  pdf: 'w-full px-4 py-5 sm:px-6 lg:px-8 pb-[max(1rem,env(safe-area-inset-bottom))]',
  documents: 'w-full px-4 py-5 sm:px-6 lg:px-8 pb-[max(1rem,env(safe-area-inset-bottom))]',
  bank: 'w-full px-4 py-5 sm:px-6 lg:px-8 pb-[max(1rem,env(safe-area-inset-bottom))]',
  tenders: 'mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8 pb-[max(1rem,env(safe-area-inset-bottom))]',
  attendance: 'mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8 pb-[max(1rem,env(safe-area-inset-bottom))]',
  etl: 'mx-auto w-full max-w-[1500px] px-4 py-5 sm:px-6 lg:px-8 pb-[max(1rem,env(safe-area-inset-bottom))]',
  sql: 'w-full px-3 py-3 sm:px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))]',
  admin:
    'mx-auto w-full max-w-6xl px-4 py-5 sm:px-6 sm:py-6 lg:px-8 pb-[max(1rem,env(safe-area-inset-bottom))]',
  messages: 'flex h-full min-h-0 flex-col px-2 py-2 sm:px-4 pb-2',
  tasks: 'mx-auto w-full max-w-[1680px] px-4 py-5 sm:px-6 lg:px-8 pb-[max(1rem,env(safe-area-inset-bottom))]',
}

const TREES: Record<SectionId, () => ReactNode> = {
  dashboard: dashboardRouteTree,
  data: dataRouteTree,
  utility: utilityRouteTree,
  letterhead: letterheadRouteTree,
  pdf: pdfToolsRouteTree,
  documents: documentsRouteTree,
  bank: bankRouteTree,
  tenders: tendersRouteTree,
  attendance: attendanceRouteTree,
  etl: etlRouteTree,
  sql: sqlRouteTree,
  admin: adminRouteTree,
  messages: messagesRouteTree,
  tasks: tasksRouteTree,
}

function matchSection(pathname: string): SectionId | null {
  if (pathname.startsWith('/dashboard')) return 'dashboard'
  if (pathname.startsWith('/data')) return 'data'
  if (pathname.startsWith('/utility')) return 'utility'
  if (pathname.startsWith('/letterhead')) return 'letterhead'
  if (pathname.startsWith('/pdf-tools')) return 'pdf'
  if (pathname.startsWith('/documents')) return 'documents'
  if (pathname.startsWith('/bank')) return 'bank'
  if (pathname.startsWith('/tenders')) return 'tenders'
  if (pathname.startsWith('/attendance')) return 'attendance'
  if (pathname.startsWith('/etl')) return 'etl'
  if (pathname.startsWith('/sql')) return 'sql'
  if (pathname.startsWith('/admin')) return 'admin'
  if (pathname.startsWith('/messages')) return 'messages'
  if (pathname.startsWith('/tasks')) return 'tasks'
  return null
}

function useFrozenSection(id: SectionId, location: Location, active: boolean) {
  const [mounted, setMounted] = useState(active)
  const [frozen, setFrozen] = useState(location)

  if (active && !mounted) setMounted(true)
  if (active && (frozen.pathname !== location.pathname || frozen.search !== location.search)) {
    setFrozen(location)
  }

  return { id, mounted, active, location: frozen }
}

function KeepAlivePane({
  active,
  className,
  children,
}: {
  active: boolean
  className: string
  children: ReactNode
}) {
  useLayoutEffect(() => {
    if (!active) return
    window.dispatchEvent(new Event('resize'))
  }, [active])

  return (
    <div
      className={`${className} page-enter`}
      hidden={!active}
      aria-hidden={!active}
      inert={!active ? true : undefined}
    >
      {children}
    </div>
  )
}

export function WorkspacePanes() {
  const location = useLocation()
  const current = matchSection(location.pathname)

  const dashboard = useFrozenSection('dashboard', location, current === 'dashboard')
  const data = useFrozenSection('data', location, current === 'data')
  const utility = useFrozenSection('utility', location, current === 'utility')
  const letterhead = useFrozenSection('letterhead', location, current === 'letterhead')
  const pdf = useFrozenSection('pdf', location, current === 'pdf')
  const documents = useFrozenSection('documents', location, current === 'documents')
  const bank = useFrozenSection('bank', location, current === 'bank')
  const tenders = useFrozenSection('tenders', location, current === 'tenders')
  const attendance = useFrozenSection('attendance', location, current === 'attendance')
  const etl = useFrozenSection('etl', location, current === 'etl')
  const sql = useFrozenSection('sql', location, current === 'sql')
  const admin = useFrozenSection('admin', location, current === 'admin')
  const messages = useFrozenSection('messages', location, current === 'messages')
  const tasks = useFrozenSection('tasks', location, current === 'tasks')

  return (
    <>
      {[dashboard, data, utility, letterhead, pdf, documents, bank, tenders, attendance, etl, sql, admin, messages, tasks].map(
        (section) =>
          section.mounted && (
            <KeepAlivePane key={section.id} active={section.active} className={PANE_CLASS[section.id]}>
              <Routes location={section.location}>{TREES[section.id]()}</Routes>
            </KeepAlivePane>
          ),
      )}
    </>
  )
}

export function isWorkspacePath(pathname: string) {
  return matchSection(pathname) !== null
}
