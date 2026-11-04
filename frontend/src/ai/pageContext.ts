import type { AiPageContext } from '../types'

/*
 * What the Copilot is told about where the person is. Only the facts that help it answer ("this dashboard", "these
 * filters", "this record") are sent; the server checks each one again and drops anything it does not recognise.
 */

const AREAS: [prefix: string, area: string, title: string][] = [
  ['/dashboard/tally', 'dashboard_tally', 'Tally dashboards'],
  ['/dashboard', 'dashboard', 'Orion dashboards'],
  ['/data', 'data', 'Data'],
  ['/utility', 'billing', 'Billing'],
  ['/letterhead', 'letterhead', 'Letterhead'],
  ['/documents', 'documents', 'Documents'],
  ['/bank', 'bank', 'Bank'],
  ['/tenders', 'tenders', 'Tenders'],
  ['/attendance', 'attendance', 'Attendance'],
  ['/etl', 'etl', 'ETL'],
  ['/admin', 'admin', 'Admin'],
  ['/messages', 'messages', 'Messages'],
  ['/tasks', 'tasks', 'Tasks'],
  ['/settings', 'settings', 'Settings'],
]

const VIEW_TITLES: Record<string, string> = {
  overview: 'Executive overview',
  revenue: 'Revenue',
  collections: 'Collections',
  profitability: 'Profitability',
  people: 'People',
  pipeline: 'Pipeline',
  fleet: 'Fleet',
  controls: 'Controls',
  cash: 'Cash',
}

const TALLY_VIEW_TITLES: Record<string, string> = {
  overview: 'billing overview',
  billing: 'billing activity',
  'credit-notes': 'credit notes',
  income: 'income mix',
  clients: 'clients and debtors',
  books: 'books snapshot',
}

/** The page's own state, from its address. Pages with more to say (an open record) add it with `useAssistantPage`. */
export function contextFromLocation(pathname: string, search: string): AiPageContext {
  if (pathname === '/') return { path: '/', area: 'home', title: 'Home' }
  const found = AREAS.find(([prefix]) => pathname.startsWith(prefix))
  const context: AiPageContext = { path: pathname, area: found ? found[1] : 'other', title: found ? found[2] : undefined }
  if (found && (found[1] === 'dashboard' || found[1] === 'dashboard_tally')) {
    const tally = found[1] === 'dashboard_tally'
    const view = pathname.split('/')[tally ? 4 : 3] || 'overview'
    context.view = view
    context.title = tally ? `Tally ${TALLY_VIEW_TITLES[view] ?? view} dashboard` : `${VIEW_TITLES[view] ?? view} dashboard`
    const filters: Record<string, string> = {}
    new URLSearchParams(search).forEach((value, key) => {
      if (value) filters[key] = value
    })
    // A dashboard with no period chosen shows the financial year we are in, so that is what the Copilot is told too.
    if (!['month', 'fy', 'from', 'to'].some((key) => filters[key])) filters.fy = 'current'
    if (Object.keys(filters).length) context.filters = filters
  }
  return context
}

/** A short, human description of the context, for the chip above the message box. */
export function describeContext(context: AiPageContext): string {
  const bits: string[] = []
  if (context.title) bits.push(context.title)
  if (context.entity) bits.push(`${context.entity}${context.entity_id ? ` ${context.entity_id}` : ''}`)
  const filters = context.filters ? Object.entries(context.filters) : []
  const range = filters.find(([key]) => key === 'from')?.[1]
  const to = filters.find(([key]) => key === 'to')?.[1]
  if (range || to) bits.push(`${range ?? '…'} to ${to ?? '…'}`)
  const others = filters.filter(([key]) => key !== 'from' && key !== 'to').length
  if (others) bits.push(`${others} filter${others === 1 ? '' : 's'}`)
  if (context.selected?.length) bits.push(`${context.selected.length} selected`)
  return bits.join(' · ')
}
