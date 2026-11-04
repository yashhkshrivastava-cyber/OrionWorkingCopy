import type { CSSProperties } from 'react'
import type { LucideIcon } from 'lucide-react'

/**
 * An icon on a small coloured tile, for lists of things (files, folders, people): the colour says what kind of thing it is, so a long list can be
 * scanned by colour. The size follows the `h-N` the plain icon was asked for, so it drops in where the bare icon was.
 */
export function IconTile({ icon: Icon, hue, className = 'h-5 w-5' }: { icon: LucideIcon; hue: string; className?: string }) {
  const n = Number(/h-(\d+)/.exec(className)?.[1] ?? 5)
  const tile = n >= 10 ? 'h-14 w-14 rounded-2xl' : n >= 6 ? 'h-10 w-10 rounded-xl' : n >= 5 ? 'h-9 w-9 rounded-xl' : 'h-7 w-7 rounded-lg'
  const glyph = n >= 10 ? 'h-7 w-7' : n >= 6 ? 'h-5 w-5' : n >= 5 ? 'h-[18px] w-[18px]' : 'h-4 w-4'
  return (
    <span style={{ '--hue': `var(--lumen-${hue})` } as CSSProperties} className={`lumen-chip inline-grid shrink-0 place-items-center ${tile}`}>
      <Icon className={glyph} aria-hidden="true" />
    </span>
  )
}
