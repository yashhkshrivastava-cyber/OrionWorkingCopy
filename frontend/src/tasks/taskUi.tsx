import type { ReactNode } from 'react'
import { ArrowDown, ArrowUp, BookOpen, Bug, CheckSquare, ChevronsUp, CornerDownRight, Layers, Minus, Repeat2, type LucideIcon } from 'lucide-react'
import { UserAvatar } from '../components/UserAvatar'
import type { StatusCategory, TaskKind, TaskPerson, TaskPriority } from '../types'

export const PRIORITIES: TaskPriority[] = ['Critical', 'High', 'Medium', 'Low']
export const KINDS: TaskKind[] = ['Task', 'Bug', 'Story', 'Epic', 'Sub-task', 'Follow-up']

const PRIORITY_LOOK: Record<TaskPriority, { icon: LucideIcon; tone: string }> = {
  Critical: { icon: ChevronsUp, tone: 'text-negative' },
  High: { icon: ArrowUp, tone: 'text-warning' },
  Medium: { icon: Minus, tone: 'text-accent' },
  Low: { icon: ArrowDown, tone: 'text-[color:var(--color-text-faint)]' },
}

const KIND_ICON: Record<TaskKind, LucideIcon> = {
  Task: CheckSquare,
  Bug: Bug,
  Story: BookOpen,
  Epic: Layers,
  'Sub-task': CornerDownRight,
  'Follow-up': Repeat2,
}

const KIND_TONE: Record<TaskKind, string> = {
  Task: 'text-accent',
  Bug: 'text-negative',
  Story: 'text-positive',
  Epic: 'text-violet',
  'Sub-task': 'text-[color:var(--color-text-muted)]',
  'Follow-up': 'text-warning',
}

export const CATEGORY_LABEL: Record<StatusCategory, string> = { todo: 'To do', doing: 'In progress', review: 'In review', done: 'Done' }

const CATEGORY_TONE: Record<StatusCategory, string> = {
  todo: 'bg-muted text-[color:var(--color-text-muted)]',
  doing: 'bg-accent-dim text-accent',
  review: 'bg-violet-dim text-violet',
  done: 'bg-positive-dim text-positive',
}

export function KindIcon({ kind, className = 'h-4 w-4' }: { kind: TaskKind; className?: string }) {
  const Icon = KIND_ICON[kind] ?? CheckSquare
  return <Icon aria-label={kind} className={`${className} shrink-0 ${KIND_TONE[kind] ?? ''}`} />
}

export function PriorityMark({ priority, withLabel = false }: { priority: TaskPriority; withLabel?: boolean }) {
  const look = PRIORITY_LOOK[priority] ?? PRIORITY_LOOK.Medium
  const Icon = look.icon
  return (
    <span className={`inline-flex items-center gap-1 ${look.tone}`} title={`${priority} priority`}>
      <Icon aria-label={`${priority} priority`} className="h-4 w-4 shrink-0" />
      {withLabel && <span className="text-xs font-medium">{priority}</span>}
    </span>
  )
}

export function StatusPill({ name, category }: { name: string; category: StatusCategory }) {
  return <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ${CATEGORY_TONE[category]}`}>{name}</span>
}

export function Person({ person, size = 'sm', name = true }: { person: TaskPerson | null; size?: 'sm' | 'xs'; name?: boolean }) {
  if (!person) return <span className="text-xs text-[color:var(--color-text-faint)]">Unassigned</span>
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <UserAvatar user={person} size="sm" className={size === 'xs' ? '!h-5 !w-5 !text-[10px]' : '!h-6 !w-6 !text-[11px]'} />
      {name && <span className="truncate text-sm text-[color:var(--color-text)]">{person.display_name}</span>}
    </span>
  )
}

/** Today as a `YYYY-MM-DD` day in this computer's time zone (the server's days are the same kind of day). */
export function todayIso(offsetDays = 0): string {
  const day = new Date()
  day.setDate(day.getDate() + offsetDays)
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
}

/** "4 Nov" (and the year when it is not this year). */
export function formatDay(iso: string | null | undefined): string {
  if (!iso) return ''
  const day = new Date(`${iso.slice(0, 10)}T00:00:00`)
  if (Number.isNaN(day.getTime())) return ''
  const sameYear = day.getFullYear() === new Date().getFullYear()
  return day.toLocaleDateString('en-IN', sameYear ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' })
}

export function DueLabel({ due, overdue, done = false }: { due: string | null; overdue: boolean; done?: boolean }): ReactNode {
  if (!due) return null
  const late = overdue && !done
  const today = due === todayIso()
  return (
    <span className={`whitespace-nowrap text-xs ${late ? 'font-semibold text-negative' : today && !done ? 'font-semibold text-warning' : 'text-[color:var(--color-text-muted)]'}`}>
      {late ? 'Overdue · ' : today && !done ? 'Today · ' : ''}
      {formatDay(due)}
    </span>
  )
}

/** 90 → "1h 30m". */
export function formatMinutes(minutes: number | null | undefined): string {
  const total = Math.max(0, Math.round(minutes ?? 0))
  if (!total) return '0m'
  const hours = Math.floor(total / 60)
  const rest = total % 60
  return `${hours ? `${hours}h` : ''}${hours && rest ? ' ' : ''}${rest ? `${rest}m` : ''}`
}

/** "1h 30m", "90", "1.5h", "2d" (a working day is eight hours) → minutes, or null when it cannot be understood. */
export function parseDuration(text: string): number | null {
  const clean = text.trim().toLowerCase()
  if (!clean) return null
  if (/^\d+$/.test(clean)) return Number(clean)
  const parts = [...clean.matchAll(/(\d+(?:\.\d+)?)\s*(d|h|m)/g)]
  if (!parts.length || parts.map((part) => part[0]).join('').replace(/\s/g, '') !== clean.replace(/\s/g, '')) return null
  const minutes = parts.reduce((sum, [, amount, unit]) => sum + Number(amount) * (unit === 'd' ? 480 : unit === 'h' ? 60 : 1), 0)
  return Math.round(minutes)
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

/** Where a task opens: on its project's board when it is known, otherwise on the page that is open. */
export function taskHref(key: string): string {
  return `/tasks/mine?task=${encodeURIComponent(key)}`
}

export function errorText(error: unknown, fallback = 'That did not work. Try again.'): string {
  return error instanceof Error && error.message ? error.message : fallback
}
