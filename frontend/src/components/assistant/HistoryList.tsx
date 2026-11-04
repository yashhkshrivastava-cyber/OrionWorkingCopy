import { useEffect, useRef, useState } from 'react'
import { Check, MessageSquareText, Pencil, Search, Trash2, X } from 'lucide-react'
import { useAssistant } from '../../ai/AssistantContext'
import type { AiCategory, AiConversation } from '../../types'

const CATEGORIES: { id: AiCategory | ''; label: string }[] = [
  { id: '', label: 'All' },
  { id: 'analytics', label: 'Analytics' },
  { id: 'reports', label: 'Reports' },
  { id: 'records', label: 'Records' },
  { id: 'tasks', label: 'Tasks' },
  { id: 'general', label: 'General' },
]

function groupOf(stamp: string): string {
  const day = new Date(stamp)
  const today = new Date()
  const days = Math.floor((new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime() - new Date(day.getFullYear(), day.getMonth(), day.getDate()).getTime()) / 86_400_000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return 'This week'
  if (days < 31) return 'This month'
  return 'Older'
}

function Row({ item, active }: { item: AiConversation; active: boolean }) {
  const { openConversation, renameConversation, deleteConversation, setCategory } = useAssistant()
  const [editing, setEditing] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [name, setName] = useState(item.title)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) input.current?.select()
  }, [editing])

  const save = async () => {
    const next = name.trim()
    setEditing(false)
    if (next && next !== item.title) await renameConversation(item.id, next).catch(() => setName(item.title))
    else setName(item.title)
  }

  if (editing) {
    return (
      <li className="flex items-center gap-1.5 rounded-lg bg-muted px-2 py-1.5">
        <input
          ref={input}
          value={name}
          maxLength={120}
          aria-label="Conversation name"
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void save()
            if (event.key === 'Escape') {
              setName(item.title)
              setEditing(false)
            }
          }}
          className="min-w-0 flex-1 rounded border border-[color:var(--color-border-strong)] bg-[color:var(--color-bg)] px-2 py-1 text-sm outline-none focus:border-[color:var(--color-primary)]"
        />
        <button type="button" onClick={() => void save()} aria-label="Save name" className="interactive rounded p-1 text-positive hover:bg-surface">
          <Check className="h-4 w-4" />
        </button>
      </li>
    )
  }

  if (confirming) {
    return (
      <li className="flex items-center justify-between gap-2 rounded-lg bg-negative-dim px-3 py-2">
        <span className="min-w-0 truncate text-sm font-medium text-negative">Delete “{item.title}”?</span>
        <span className="flex shrink-0 gap-1">
          <button type="button" onClick={() => setConfirming(false)} className="interactive rounded-md px-2 py-1 text-xs font-semibold hover:bg-surface">
            Keep
          </button>
          <button type="button" onClick={() => void deleteConversation(item.id)} className="interactive rounded-md bg-negative px-2 py-1 text-xs font-semibold text-on-negative">
            Delete
          </button>
        </span>
      </li>
    )
  }

  return (
    <li className={`group relative rounded-lg ${active ? 'bg-accent-dim' : 'hover:bg-muted'}`}>
      <button type="button" onClick={() => void openConversation(item.id)} className="flex w-full items-start gap-2.5 px-2.5 py-2 text-left">
        <MessageSquareText className="mt-0.5 h-4 w-4 shrink-0 text-[color:var(--color-text-faint)]" aria-hidden="true" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{item.title}</span>
          {item.preview && <span className="block truncate text-xs text-[color:var(--color-text-muted)]">{item.preview.replace(/\[Looked up[^\]]*\]/g, '').trim()}</span>}
        </span>
      </button>
      <span className="absolute right-1.5 top-1.5 hidden items-center gap-0.5 rounded-md bg-surface/95 p-0.5 shadow-card group-focus-within:flex group-hover:flex">
        <select
          value={item.category}
          aria-label="Category"
          onChange={(event) => void setCategory(item.id, event.target.value as AiCategory)}
          className="rounded bg-transparent px-1 py-0.5 text-[11px] text-[color:var(--color-text-muted)] outline-none hover:bg-muted"
        >
          {CATEGORIES.filter((c) => c.id).map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}
            </option>
          ))}
        </select>
        <button type="button" onClick={() => setEditing(true)} aria-label={`Rename ${item.title}`} className="interactive rounded p-1 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]">
          <Pencil className="h-3.5 w-3.5" />
        </button>
        <button type="button" onClick={() => setConfirming(true)} aria-label={`Delete ${item.title}`} className="interactive rounded p-1 text-[color:var(--color-text-muted)] hover:bg-negative-dim hover:text-negative">
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </span>
    </li>
  )
}

/** Saved conversations: search, filter by kind, rename, delete, and carry on from where you stopped. */
export function HistoryList() {
  const { conversations, loadConversations, activeId, newChat, status } = useAssistant()
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<AiCategory | ''>('')

  useEffect(() => {
    const timer = window.setTimeout(() => void loadConversations(query, category), query ? 220 : 0)
    return () => window.clearTimeout(timer)
  }, [query, category, loadConversations])

  const groups: [string, AiConversation[]][] = []
  for (const item of conversations) {
    const label = groupOf(item.updated_timestamp)
    const last = groups[groups.length - 1]
    if (last && last[0] === label) last[1].push(item)
    else groups.push([label, [item]])
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-2.5 px-3 pb-2 pt-3">
        <label className="relative block">
          <span className="sr-only">Search conversations</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search conversations"
            className="h-9 w-full rounded-lg border border-[color:var(--color-border-strong)] bg-[color:var(--color-bg)] pl-9 pr-8 text-sm outline-none focus:border-[color:var(--color-primary)]"
          />
          {query && (
            <button type="button" onClick={() => setQuery('')} aria-label="Clear search" className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-[color:var(--color-text-faint)] hover:text-[color:var(--color-text)]">
              <X className="h-4 w-4" />
            </button>
          )}
        </label>
        <div className="scroll-quiet -mx-1 flex gap-1.5 overflow-x-auto px-1" role="tablist" aria-label="Kind of conversation">
          {CATEGORIES.map((c) => (
            <button
              key={c.id || 'all'}
              type="button"
              role="tab"
              aria-selected={category === c.id}
              onClick={() => setCategory(c.id)}
              className={`interactive shrink-0 rounded-full px-3 py-1 text-xs font-medium ${category === c.id ? 'bg-accent-dim text-accent' : 'text-[color:var(--color-text-muted)] hover:bg-muted'}`}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {groups.length === 0 ? (
          <div className="px-4 py-10 text-center">
            <p className="text-sm font-medium">{query || category ? 'No conversations match.' : 'No conversations yet.'}</p>
            <p className="t-caption mt-1">
              {status?.settings.keep_history === false
                ? 'You have chosen not to keep history, so conversations are not saved.'
                : 'Start one and it will be saved here, ready to continue.'}
            </p>
            <button type="button" onClick={newChat} className="btn-primary interactive mt-4 h-8 rounded-lg px-3 text-xs font-semibold">
              New conversation
            </button>
          </div>
        ) : (
          groups.map(([label, items]) => (
            <section key={label} className="mt-2">
              <h3 className="eyebrow px-2.5 py-1">{label}</h3>
              <ul className="space-y-0.5">
                {items.map((item) => (
                  <Row key={item.id} item={item} active={item.id === activeId} />
                ))}
              </ul>
            </section>
          ))
        )}
      </div>
    </div>
  )
}
