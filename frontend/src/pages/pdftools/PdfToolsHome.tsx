import { Link } from 'react-router-dom'
import { FileUp, ShieldCheck } from 'lucide-react'
import { TabLink } from '../../components/ui/TabLink'
import { GROUPS, TOOLS } from './tools'

/** The tools, in groups. Each opens its own screen at /pdf-tools/<tool>. */
export function PdfToolsHome() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-6">
      <div>
        <h1 className="t-h1 text-[color:var(--color-text)]">PDF tools</h1>
        <p className="mt-1 max-w-3xl text-sm text-[color:var(--color-text-muted)]">
          Merge, split, compress, rotate, lock and more, for the PDFs you send and file every day. Your files are worked on in the server&apos;s memory and forgotten the moment
          you have your result: nothing is saved, and no one else can see them.
        </p>
      </div>

      {GROUPS.map((group) => (
        <section key={group} aria-labelledby={`group-${group}`} className="space-y-3">
          <h2 id={`group-${group}`} className="t-h3 text-[color:var(--color-text)]">
            {group}
          </h2>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {TOOLS.filter((tool) => tool.group === group).map((tool) => {
              const Icon = tool.icon
              return (
                <li key={tool.id}>
                  <Link
                    to={`/pdf-tools/${tool.id}`}
                    className="group flex h-full flex-col gap-2 rounded-xl border border-[color:var(--color-border)] bg-surface p-4 transition-colors hover:border-[color:var(--color-accent)] hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-accent"
                  >
                    <span className="inline-flex w-fit rounded-lg bg-accent-dim p-2 text-accent" aria-hidden="true">
                      <Icon className="h-5 w-5" />
                    </span>
                    <span className="text-sm font-semibold text-[color:var(--color-text)]">{tool.title}</span>
                    <span className="text-xs text-[color:var(--color-text-muted)]">{tool.blurb}</span>
                  </Link>
                </li>
              )
            })}
            {group === 'Edit and mark' && (
              <li>
                <TabLink
                  to="/letterhead/pdf"
                  className="group flex h-full flex-col gap-2 rounded-xl border border-dashed border-[color:var(--color-border-strong)] bg-surface p-4 transition-colors hover:border-[color:var(--color-accent)] hover:bg-surface-hover"
                >
                  <span className="inline-flex w-fit rounded-lg bg-accent-dim p-2 text-accent" aria-hidden="true">
                    <FileUp className="h-5 w-5" />
                  </span>
                  <span className="text-sm font-semibold text-[color:var(--color-text)]">Put a PDF on the letterhead</span>
                  <span className="text-xs text-[color:var(--color-text-muted)]">Add the company header and footer to a PDF made elsewhere. It has its own tool in Letterhead.</span>
                </TabLink>
              </li>
            )}
          </ul>
        </section>
      ))}

      <p className="flex items-start gap-2 text-xs text-[color:var(--color-text-muted)]">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
        Locking a PDF uses a password only you know: Orion does not keep it and cannot recover it. Unlocking needs the password too: Orion does not guess or break passwords.
      </p>
    </div>
  )
}
