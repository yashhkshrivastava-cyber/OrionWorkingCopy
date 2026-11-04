import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { CornerDownLeft, History, MessageSquareText, Moon, Search, Settings2, Sparkles, SquarePen, Sun, type LucideIcon } from 'lucide-react'
import { useAssistant } from '../../ai/AssistantContext'
import { useAppearance } from '../../context/AppearanceContext'
import { useDialog } from '../../hooks/useDialog'
import { usePresence } from '../../hooks/usePresence'

export type Destination = { label: string; to: string; icon: LucideIcon; group: string }

type Entry = { id: string; label: string; hint?: string; icon: LucideIcon; group: string; run: () => void }

/**
 * Ctrl+K: one box for asking the Copilot, jumping to a page, and running the common commands. Anything typed can be
 * sent to the Copilot as a question with Enter.
 */
export function CommandPalette({ destinations }: { destinations: Destination[] }) {
  const a = useAssistant()
  const appearance = useAppearance()
  const navigate = useNavigate()
  const { present, leaving } = usePresence(a.paletteOpen)
  const panel = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const titleId = useId()
  const close = () => a.setPaletteOpen(false)
  useDialog(panel, a.paletteOpen, close)

  const { loadConversations } = a
  useEffect(() => {
    if (a.paletteOpen) {
      setQuery('')
      setIndex(0)
      void loadConversations()
    }
  }, [a.paletteOpen, loadConversations])

  const entries = useMemo<Entry[]>(() => {
    const text = query.trim()
    const lower = text.toLowerCase()
    const out: Entry[] = []
    if (text) {
      out.push({ id: 'ask', label: `Ask the Copilot: “${text.length > 70 ? text.slice(0, 70) + '…' : text}”`, icon: Sparkles, group: 'Ask', run: () => a.ask(text) })
    }
    const matches = (label: string) => !lower || label.toLowerCase().includes(lower)
    const dark = appearance.mode === 'dark'
    const actions: Entry[] = [
      { id: 'new', label: 'New conversation', icon: SquarePen, group: 'Copilot', run: () => { a.newChat(); a.setOpen(true) } },
      { id: 'history', label: 'Conversations', icon: History, group: 'Copilot', run: () => { a.setOpen(true); a.setScreen('history') } },
      { id: 'mode', label: dark ? 'Switch to light mode' : 'Switch to dark mode', icon: dark ? Sun : Moon, group: 'Actions', run: () => appearance.update({ mode: dark ? 'light' : 'dark' }, { fade: true }) },
      { id: 'interface', label: appearance.prefs.experience === 'lumen' ? 'Switch to the classic look' : 'Switch to the new look (Lumen)', icon: Sparkles, group: 'Actions', run: () => appearance.setExperience(appearance.prefs.experience === 'lumen' ? 'classic' : 'lumen') },
      { id: 'settings', label: 'Copilot settings', icon: Settings2, group: 'Actions', run: () => navigate('/settings?tab=ai') },
    ]
    out.push(...actions.filter((entry) => matches(entry.label)))
    out.push(...destinations.filter((d) => matches(d.label)).map((d) => ({ id: `go-${d.to}`, label: d.label, hint: 'Go to', icon: d.icon, group: 'Go to', run: () => navigate(d.to) })))
    out.push(
      ...a.conversations
        .filter((c) => matches(c.title))
        .slice(0, text ? 6 : 4)
        .map((c) => ({ id: `chat-${c.id}`, label: c.title, hint: 'Conversation', icon: MessageSquareText, group: 'Recent conversations', run: () => { a.setOpen(true); void a.openConversation(c.id) } })),
    )
    if (!text) {
      out.push(...a.suggestions.slice(0, 4).map((s) => ({ id: `s-${s}`, label: s, icon: Sparkles, group: 'Try asking', run: () => a.ask(s) })))
    }
    return out
  }, [query, a, appearance, destinations, navigate])

  useEffect(() => setIndex(0), [query])
  useEffect(() => {
    list.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [index])

  if (!present) return null

  const run = (entry: Entry | undefined) => {
    if (!entry) return
    close()
    entry.run()
  }

  let lastGroup = ''
  const rows: ReactNode[] = []
  entries.forEach((entry, at) => {
    if (entry.group !== lastGroup) {
      lastGroup = entry.group
      rows.push(
        <li key={`g-${entry.group}`} role="presentation" className="eyebrow px-3 pb-1 pt-3">
          {entry.group}
        </li>,
      )
    }
    const Icon = entry.icon
    rows.push(
      <li
        key={entry.id}
        id={`${titleId}-${at}`}
        role="option"
        aria-selected={at === index}
        onMouseMove={() => setIndex(at)}
        onClick={() => run(entry)}
        className={`flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm ${at === index ? 'bg-accent-dim text-[color:var(--color-text)]' : ''}`}
      >
        <Icon className={`h-4 w-4 shrink-0 ${at === index ? 'text-accent' : 'text-[color:var(--color-text-faint)]'}`} aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate">{entry.label}</span>
        {at === index && <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-[color:var(--color-text-faint)]" aria-hidden="true" />}
      </li>,
    )
  })

  return createPortal(
    <div className="fixed inset-0 z-[90] flex items-start justify-center px-3 pt-[12vh]">
      <button
        type="button"
        tabIndex={-1}
        aria-label="Close"
        className={`${leaving ? 'backdrop-out' : 'backdrop-in'} absolute inset-0 bg-scrim backdrop-blur-[2px]`}
        onClick={close}
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`${leaving ? 'modal-out' : 'modal-in'} overlay relative w-full max-w-xl overflow-hidden rounded-2xl border border-[color:var(--color-border)] outline-none`}
      >
        <h2 id={titleId} className="sr-only">
          Command palette
        </h2>
        <div className="flex items-center gap-3 border-b border-[color:var(--color-border)] px-4">
          <Search className="h-4 w-4 shrink-0 text-[color:var(--color-text-faint)]" aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ask anything, or jump to a page…"
            aria-label="Ask anything, or jump to a page"
            role="combobox"
            aria-expanded="true"
            aria-controls={`${titleId}-list`}
            aria-activedescendant={`${titleId}-${index}`}
            data-autofocus
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setIndex((value) => Math.min(entries.length - 1, value + 1))
              } else if (event.key === 'ArrowUp') {
                event.preventDefault()
                setIndex((value) => Math.max(0, value - 1))
              } else if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                event.preventDefault()
                run(entries[index])
              }
            }}
            className="h-12 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-[color:var(--color-text-faint)]"
          />
          <kbd className="hidden rounded border border-[color:var(--color-border)] px-1.5 py-0.5 text-[10px] font-medium text-[color:var(--color-text-faint)] sm:block">Esc</kbd>
        </div>
        <ul ref={list} id={`${titleId}-list`} role="listbox" className="max-h-[52vh] overflow-y-auto p-1.5">
          {rows.length ? rows : <li className="px-3 py-6 text-center text-sm text-[color:var(--color-text-muted)]">Nothing matches. Press Enter to ask the Copilot.</li>}
        </ul>
        <div className="flex items-center gap-4 border-t border-[color:var(--color-border)] px-4 py-2 text-[11px] text-[color:var(--color-text-faint)]">
          <span>↑↓ to move</span>
          <span>Enter to choose</span>
          <span className="ml-auto">Ctrl+J opens the Copilot</span>
        </div>
      </div>
    </div>,
    document.body,
  )
}
