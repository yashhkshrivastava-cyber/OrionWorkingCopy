import { useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'

/** A row of mutually exclusive choices, shown together so the options are visible without opening anything. */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { id: T; label: string }[]
  onChange: (next: T) => void
}) {
  const list = useRef<HTMLDivElement>(null)
  const buttons = useRef(new Map<string, HTMLButtonElement>())
  const [thumb, setThumb] = useState<{ left: number; width: number } | null>(null)

  useLayoutEffect(() => {
    const measure = () => {
      const node = buttons.current.get(value)
      setThumb(node ? { left: node.offsetLeft, width: node.offsetWidth } : null)
    }
    measure()
    const observer = new ResizeObserver(measure)
    if (list.current) observer.observe(list.current)
    return () => observer.disconnect()
  }, [value, options])

  const onKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0
    if (!step) return
    event.preventDefault()
    const next = options[(index + step + options.length) % options.length]
    onChange(next.id)
    buttons.current.get(next.id)?.focus()
  }

  return (
    <div
      ref={list}
      role="radiogroup"
      aria-label={label}
      className="scroll-quiet relative inline-flex max-w-full gap-0.5 overflow-x-auto rounded-lg bg-muted p-0.5"
    >
      {thumb && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute bottom-0.5 top-0.5 rounded-md bg-surface shadow-card transition-[transform,width] duration-[var(--orion-dur-base)] ease-[var(--orion-ease)]"
          style={{ width: thumb.width, transform: `translateX(${thumb.left}px)`, left: 0 }}
        />
      )}
      {options.map((option, index) => {
        const active = option.id === value
        return (
          <button
            key={option.id}
            ref={(node) => {
              if (node) buttons.current.set(option.id, node)
              else buttons.current.delete(option.id)
            }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(option.id)}
            onKeyDown={(event) => onKey(event, index)}
            className={`interactive relative z-[1] shrink-0 whitespace-nowrap rounded-md px-2.5 py-1 text-xs font-medium ${
              active ? 'text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
