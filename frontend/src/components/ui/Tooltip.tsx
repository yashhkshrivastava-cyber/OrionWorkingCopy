import { cloneElement, useId, type ReactElement } from 'react'

/**
 * A short label that appears over a control on hover and on keyboard focus, and is read out by screen readers as the
 * control's description. It is made of CSS (no listeners, no re-render), so it costs nothing until it is shown.
 * Wrap exactly one element; for an icon-only button also give the button an aria-label.
 */
export function Tooltip({
  label,
  children,
  side = 'bottom',
}: {
  label: string
  children: ReactElement<{ 'aria-describedby'?: string }>
  side?: 'top' | 'bottom'
}) {
  const id = useId()
  return (
    <span className="group/tip relative inline-flex">
      {cloneElement(children, { 'aria-describedby': id })}
      <span
        id={id}
        role="tooltip"
        className={`pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 whitespace-nowrap rounded-md bg-[color:var(--color-text)] px-2 py-1 text-xs font-medium text-[color:var(--color-bg)] opacity-0 shadow-raised transition-opacity duration-[var(--orion-dur-fast)] group-hover/tip:opacity-100 group-focus-within/tip:opacity-100 ${
          side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5'
        }`}
      >
        {label}
      </span>
    </span>
  )
}
