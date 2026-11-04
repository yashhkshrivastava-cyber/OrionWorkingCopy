import {
  BookOpenText,
  Building2,
  CalendarCheck,
  ChartNoAxesCombined,
  Database,
  FileStack,
  FolderArchive,
  Gavel,
  Landmark,
  ListChecks,
  MessagesSquare,
  ReceiptText,
  ScrollText,
  ShieldCheck,
  TerminalSquare,
  Wallet,
  Workflow,
  type LucideIcon,
} from 'lucide-react'
import { areaOf, type NavArea } from '../../context/TabMemoryContext'
import type { User } from '../../types'

export type NavItem = {
  area: NavArea
  label: string
  icon: LucideIcon
  visible: (user: User) => boolean
}

/** The rail, top to bottom. An item is one click from anywhere and remembers where you left it. */
export const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: 'Insights',
    items: [
      {
        area: 'dashboard.orion',
        label: 'Orion dashboards',
        icon: ChartNoAxesCombined,
        visible: (user) => user.pages.includes('dashboard') && user.can_orion_dashboard !== false,
      },
      {
        area: 'dashboard.tally',
        label: 'Tally dashboards',
        icon: Landmark,
        visible: (user) => user.pages.includes('dashboard') && user.can_tally_dashboard === true,
      },
    ],
  },
  {
    label: 'Data',
    items: [
      {
        area: 'data.orion',
        label: 'Orion data',
        icon: Database,
        visible: (user) =>
          user.pages.includes('data') && Boolean(user.can_ods || user.can_ods_write || user.can_dw || user.can_dw_write),
      },
      {
        area: 'data.tally',
        label: 'Tally data',
        icon: BookOpenText,
        visible: (user) =>
          user.pages.includes('data') &&
          Boolean(user.can_tally || user.can_tally_write || user.can_tally_dw || user.can_tally_dw_write),
      },
      { area: 'etl', label: 'ETL', icon: Workflow, visible: (user) => user.pages.includes('etl') },
      { area: 'sql', label: 'SQL editor', icon: TerminalSquare, visible: (user) => user.pages.includes('sql') },
    ],
  },
  {
    // Everyday tools. A new one is one more item here, with its own routes and its own access flags.
    label: 'Utilities',
    items: [
      { area: 'utility', label: 'Billing', icon: ReceiptText, visible: (user) => user.pages.includes('utility') },
      { area: 'letterhead', label: 'Letterhead', icon: ScrollText, visible: (user) => user.pages.includes('letterhead') },
      { area: 'pdf', label: 'PDF tools', icon: FileStack, visible: (user) => user.pages.includes('letterhead') },
      { area: 'documents', label: 'Documents', icon: FolderArchive, visible: (user) => user.pages.includes('documents') },
      { area: 'bank', label: 'Bank', icon: Wallet, visible: (user) => user.pages.includes('bank') },
      { area: 'tenders.gem', label: 'GeM tenders', icon: Gavel, visible: (user) => user.pages.includes('tenders') },
      { area: 'tenders.mp', label: 'MP tenders', icon: Building2, visible: (user) => user.pages.includes('tenders') },
      { area: 'attendance', label: 'Attendance', icon: CalendarCheck, visible: (user) => user.pages.includes('attendance') },
    ],
  },
  {
    label: 'Team',
    items: [
      { area: 'messages', label: 'Messages', icon: MessagesSquare, visible: () => true },
      { area: 'tasks', label: 'Tasks', icon: ListChecks, visible: () => true },
      { area: 'admin', label: 'Admin', icon: ShieldCheck, visible: (user) => user.pages.includes('admin') },
    ],
  },
]

export const roleLabel: Record<string, string> = { admin: 'Admin', editor: 'Editor', viewer: 'Viewer' }

/** What the top bar calls the page you are on. */
export function pageTitle(pathname: string): { section: string; title: string } {
  const area = areaOf(pathname)
  for (const group of NAV_GROUPS) {
    const item = group.items.find((entry) => entry.area === area)
    if (item) return { section: group.label, title: item.label }
  }
  if (pathname.startsWith('/dashboard')) return { section: 'Insights', title: 'Dashboards' }
  if (pathname.startsWith('/data')) return { section: 'Data', title: 'Data management' }
  if (pathname.startsWith('/settings')) return { section: 'Account', title: 'Settings' }
  return { section: 'Prakash Securities', title: 'Home' }
}


/** The hue each area wears in the Lumen interface (the names are variables in lumen.css). */
export const AREA_HUE: Record<NavArea, string> = {
  'dashboard.orion': 'indigo',
  'dashboard.tally': 'blue',
  'data.orion': 'cyan',
  'data.tally': 'blue',
  etl: 'teal',
  sql: 'slate',
  utility: 'coral',
  letterhead: 'amber',
  pdf: 'violet',
  documents: 'orange',
  bank: 'green',
  'tenders.gem': 'pink',
  'tenders.mp': 'pink',
  attendance: 'cyan',
  messages: 'violet',
  tasks: 'indigo',
  admin: 'slate',
}

/** A line about what each area is for, shown in the launcher. */
export const AREA_BLURB: Record<NavArea, string> = {
  'dashboard.orion': 'Revenue, people, pipeline, cash and more',
  'dashboard.tally': 'Billing and books from Tally',
  'data.orion': 'Cases, clients, employees and records',
  'data.tally': 'The Tally working copy and warehouse',
  etl: 'Pipelines that load the warehouse',
  sql: 'Ask the database anything, read-only',
  utility: 'Bills, receivables, TDS, GST, credit notes',
  letterhead: 'Letters on the company letterhead',
  pdf: 'Merge, split, compress and lock PDFs',
  documents: 'Every paper, filed and findable',
  bank: 'Balance, ledger, payables and payroll',
  'tenders.gem': 'Bids on GeM',
  'tenders.mp': 'Bids on MP Tenders',
  attendance: 'Registers that become salary',
  messages: 'Chat with the team',
  tasks: 'Projects, boards, reviews and your to-dos',
  admin: 'People, access, backups and health',
}

/** The cssvar for an area's hue, for `style={{ '--hue': hueVar(area) }}`. */
export const hueVar = (area: NavArea) => `var(--lumen-${AREA_HUE[area]})`
