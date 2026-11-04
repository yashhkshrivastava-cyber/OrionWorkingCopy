import type { ReactNode } from 'react'
import { TabLink } from '../ui/TabLink'
import { ChevronRight } from 'lucide-react'

/** The card an answer's block sits in: a title, and a link to the full page when there is one. */
export function Frame({ title, link, children }: { title?: string; link?: string | null; children: ReactNode }) {
  return (
    <figure className="panel @container overflow-hidden">
      {(title || link) && (
        <figcaption className="flex items-center justify-between gap-3 px-3.5 pt-3">
          <span className="eyebrow truncate normal-case tracking-normal text-[color:var(--color-text-muted)]">{title}</span>
          {link && (
            <TabLink to={link} className="inline-flex shrink-0 items-center gap-0.5 text-xs font-semibold text-accent hover:underline">
              View details
              <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
            </TabLink>
          )}
        </figcaption>
      )}
      {children}
    </figure>
  )
}
