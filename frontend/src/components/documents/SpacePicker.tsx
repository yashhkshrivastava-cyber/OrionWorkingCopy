import { useEffect, useState } from 'react'
import { Check, Search } from 'lucide-react'
import { api } from '../../api/client'
import type { DocScope, DocumentTargets } from '../../types'
import { Input } from '../ui/Field'
import { Segmented } from '../ui/Segmented'

/** Where a document is kept: the company, one case or one client. `label` is what to call it on screen. */
export type Space = { scope: DocScope; case_code?: string; client_code?: string; label: string }

export const sameSpace = (a: Space, b: Space) =>
  a.scope === b.scope && (a.case_code ?? '') === (b.case_code ?? '') && (a.client_code ?? '') === (b.client_code ?? '')

/** Choose the company, or find a case or client by typing part of its name or code. */
export function SpacePicker({ value, onChange }: { value: Space | null; onChange: (next: Space | null) => void }) {
  const [scope, setScope] = useState<DocScope>(value?.scope ?? 'case')
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<DocumentTargets | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (scope === 'company') return
    const timer = window.setTimeout(() => {
      api
        .documentTargets(query)
        .then((r) => {
          setFound(r)
          setError('')
        })
        .catch((e: Error) => setError(e.message))
    }, query ? 250 : 0)
    return () => window.clearTimeout(timer)
  }, [scope, query])

  const choose = (next: DocScope) => {
    setScope(next)
    setQuery('')
    onChange(next === 'company' ? { scope: 'company', label: 'Company documents' } : null)
  }

  const options: { id: string; label: string; sub: string; space: Space }[] =
    scope === 'case'
      ? (found?.cases ?? []).map((c) => ({
          id: c.case_code,
          label: c.case_name,
          sub: [c.case_code, c.client_name, c.case_status].filter(Boolean).join(' · '),
          space: { scope: 'case', case_code: c.case_code, label: c.case_name },
        }))
      : (found?.clients ?? []).map((c) => ({
          id: c.client_code,
          label: c.client_name,
          sub: c.client_code,
          space: { scope: 'client', client_code: c.client_code, label: c.client_name },
        }))

  return (
    <div className="space-y-2">
      <Segmented<DocScope>
        label="Where this belongs"
        value={scope}
        onChange={choose}
        options={[
          { id: 'case', label: 'A case' },
          { id: 'client', label: 'A client' },
          { id: 'company', label: 'The company' },
        ]}
      />
      {scope !== 'company' && (
        <>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={scope === 'case' ? 'Search cases by name, code or client' : 'Search clients by name or code'}
              className="pl-9"
              aria-label="Search"
            />
          </div>
          {error && <p className="text-xs text-negative">{error}</p>}
          <ul className="max-h-48 divide-y divide-[color:var(--color-border)] overflow-y-auto rounded-lg border border-[color:var(--color-border)]">
            {options.map((option) => {
              const chosen = value ? sameSpace(value, option.space) : false
              return (
                <li key={option.id}>
                  <button
                    type="button"
                    onClick={() => onChange(option.space)}
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted ${chosen ? 'bg-accent-dim/50' : ''}`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium text-[color:var(--color-text)]">{option.label}</span>
                      <span className="block truncate text-xs text-[color:var(--color-text-muted)]">{option.sub}</span>
                    </span>
                    {chosen && <Check className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />}
                  </button>
                </li>
              )
            })}
            {found && options.length === 0 && (
              <li className="px-3 py-3 text-sm text-[color:var(--color-text-muted)]">
                {scope === 'case' ? 'No case matches.' : 'No client matches.'}
              </li>
            )}
          </ul>
        </>
      )}
    </div>
  )
}
