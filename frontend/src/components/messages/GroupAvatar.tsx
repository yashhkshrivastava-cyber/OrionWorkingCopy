const TONES = [
  'bg-primary text-on-primary',
  'bg-violet text-[color:var(--color-bg)]',
  'bg-positive-dim text-positive',
  'bg-warning-dim text-warning',
  'bg-accent-dim text-accent',
  'bg-negative-dim text-negative',
]

const SIZES = {
  sm: 'h-8 w-8 text-xs',
  md: 'h-10 w-10 text-sm',
  row: 'h-12 w-12 text-base',
  xl: 'h-14 w-14 text-lg',
  lg: 'h-20 w-20 text-2xl',
}

/** Which of the colours a group wears: the same name always gets the same one. */
function toneFor(title: string): string {
  let hash = 0
  for (const ch of title) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  return TONES[hash % TONES.length]
}

/** A group's picture: the first letters of its name on a colour that goes with the name. */
export function GroupAvatar({ title, size = 'md', className = '' }: { title: string; size?: keyof typeof SIZES; className?: string }) {
  const words = title.trim().split(/\s+/).filter(Boolean)
  const letters = (words.length > 1 ? `${words[0][0]}${words[1][0]}` : (words[0] ?? '?').slice(0, 2)).toUpperCase()
  return (
    <span className={`inline-flex shrink-0 items-center justify-center rounded-full font-bold ${SIZES[size]} ${toneFor(title)} ${className}`} aria-hidden="true">
      {letters}
    </span>
  )
}
