import { useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'

/** A row of tabs with an underline that glides to the one chosen. Arrow keys move between tabs. */
export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
  label = 'Sections',
}: {
  tabs: { id: T; label: string }[]
  active: T
  onChange: (id: T) => void
  label?: string
}) {
  const list = useRef<HTMLDivElement>(null)
  const buttons = useRef(new Map<string, HTMLButtonElement>())
  const [bar, setBar] = useState<{ left: number; width: number } | null>(null)

  useLayoutEffect(() => {
    const measure = () => {
      const node = buttons.current.get(active)
      if (node) setBar({ left: node.offsetLeft, width: node.offsetWidth })
    }
    measure()
    const observer = new ResizeObserver(measure)
    if (list.current) observer.observe(list.current)
    return () => observer.disconnect()
  }, [active, tabs])

  const onKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (!step && event.key !== 'Home' && event.key !== 'End') return
    event.preventDefault()
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + step + tabs.length) % tabs.length
    onChange(tabs[next].id)
    buttons.current.get(tabs[next].id)?.focus()
  }

  return (
    <div
      ref={list}
      role="tablist"
      aria-label={label}
      className="scroll-quiet relative flex gap-1 overflow-x-auto border-b border-[color:var(--color-border)]"
    >
      {tabs.map((tab, index) => (
        <button
          key={tab.id}
          ref={(node) => {
            if (node) buttons.current.set(tab.id, node)
            else buttons.current.delete(tab.id)
          }}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          tabIndex={active === tab.id ? 0 : -1}
          onClick={() => onChange(tab.id)}
          onKeyDown={(event) => onKey(event, index)}
          className={`t-label interactive shrink-0 px-3 py-2.5 ${
            active === tab.id
              ? 'text-[color:var(--color-text)]'
              : 'text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]'
          }`}
        >
          {tab.label}
        </button>
      ))}
      {bar && (
        <span
          aria-hidden="true"
          className="accent-fill pointer-events-none absolute bottom-0 h-0.5 rounded-full transition-[transform,width] duration-[var(--orion-dur-base)] ease-[var(--orion-ease)]"
          style={{ width: bar.width, transform: `translateX(${bar.left}px)` }}
        />
      )}
    </div>
  )
}
