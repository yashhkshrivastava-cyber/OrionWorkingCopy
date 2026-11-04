import { useEffect, useState } from 'react'
import { ClipboardCopy, Play } from 'lucide-react'
import { api } from '../../api/client'
import type { SqlObjectDetail } from '../../types'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'
import { bytes, qualified } from './SchemaTree'

const TABS = ['Columns', 'Keys', 'Indexes', 'Triggers', 'Statistics', 'CREATE statement'] as const

/**
 * One table or view in full, as the Properties window of SSMS or pgAdmin shows it: its columns with types and defaults, its keys and who points at it, its
 * indexes and triggers, its size and statistics, and a CREATE statement to copy or to open in the editor.
 */
export function ObjectDetailModal({
  target,
  onClose,
  onOpenSql,
}: {
  target: { schema: string; name: string } | null
  onClose: () => void
  onOpenSql: (sql: string, run: boolean) => void
}) {
  const [detail, setDetail] = useState<SqlObjectDetail | null>(null)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<(typeof TABS)[number]>('Columns')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    setDetail(null)
    setError('')
    setTab('Columns')
    if (!target) return
    let stale = false
    api
      .sqlObject(target.schema, target.name)
      .then((found) => !stale && setDetail(found))
      .catch((e: Error) => !stale && setError(e.message))
    return () => {
      stale = true
    }
  }, [target])

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setError('The browser did not allow copying.')
    }
  }

  const name = target ? qualified(target.schema, target.name) : ''
  return (
    <Modal open={target !== null} title={target ? `${target.schema}.${target.name}` : ''} size="2xl" onClose={onClose}>
      {error && <Alert variant="error">{error}</Alert>}
      {!detail && !error && <p className="text-sm text-[color:var(--color-text-muted)]">Reading…</p>}
      {detail && (
        <div className="space-y-3">
          <p className="text-sm text-[color:var(--color-text-muted)]">
            {detail.kind}, owned by {detail.owner}
            {detail.estimated_rows !== null ? `, about ${detail.estimated_rows.toLocaleString('en-IN')} rows` : ''}, {bytes(detail.total_bytes)} in all
            {detail.comment ? ` · ${detail.comment}` : ''}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex flex-wrap gap-1" role="tablist" aria-label="About this object">
              {TABS.filter((t) => t !== 'Triggers' || detail.triggers.length > 0).map((t) => (
                <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={`rounded-lg px-3 py-1.5 text-sm ${tab === t ? 'bg-accent-dim font-semibold text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:bg-muted'}`}>
                  {t}
                </button>
              ))}
            </div>
            <div className="ml-auto flex gap-2">
              <Button variant="secondary" size="sm" onClick={() => onOpenSql(`SELECT *\nFROM ${name}\nLIMIT 100;`, true)}>
                <Play className="h-4 w-4" /> Preview 100 rows
              </Button>
            </div>
          </div>

          {tab === 'Columns' && (
            <div className="overflow-x-auto rounded-lg border border-[color:var(--color-border)]">
              <table className="w-full text-left text-sm">
                <thead className="bg-muted text-xs text-[color:var(--color-text-muted)]">
                  <tr>
                    <th className="px-3 py-2">#</th>
                    <th className="px-3 py-2">Column</th>
                    <th className="px-3 py-2">Type</th>
                    <th className="px-3 py-2">Null?</th>
                    <th className="px-3 py-2">Default</th>
                    <th className="px-3 py-2">Comment</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.columns.map((c, i) => (
                    <tr key={c.name} className="border-t border-[color:var(--color-border)]">
                      <td className="px-3 py-1.5 tabular-nums text-[color:var(--color-text-faint)]">{i + 1}</td>
                      <td className="px-3 py-1.5 font-medium text-[color:var(--color-text)]">{c.name}</td>
                      <td className="px-3 py-1.5 font-mono text-xs">{c.type}</td>
                      <td className="px-3 py-1.5">{c.nullable ? 'yes' : 'NOT NULL'}</td>
                      <td className="max-w-[18rem] truncate px-3 py-1.5 font-mono text-xs" title={c.default ?? ''}>{c.identity ? 'identity' : (c.default ?? '')}</td>
                      <td className="px-3 py-1.5 text-[color:var(--color-text-muted)]">{c.comment ?? ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {tab === 'Keys' && (
            <div className="space-y-3 text-sm">
              <List title="Constraints" empty="No constraints." items={detail.constraints.map((c) => ({ key: c.name, head: `${c.name} · ${c.kind}`, body: c.definition }))} />
              <List title="Pointed at by" empty="No other table points at this one." items={detail.referenced_by.map((c) => ({ key: `${c.table}.${c.name}`, head: c.table, body: c.definition }))} />
            </div>
          )}
          {tab === 'Indexes' && <List title="Indexes" empty="No indexes." items={detail.indexes.map((c) => ({ key: c.name, head: c.name, body: c.definition }))} />}
          {tab === 'Triggers' && <List title="Triggers" empty="No triggers." items={detail.triggers.map((c) => ({ key: c.name, head: c.name, body: c.definition }))} />}
          {tab === 'Statistics' && (
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[14rem_1fr]">
              {[
                ['Size with indexes', bytes(detail.total_bytes)],
                ['Size of the table', bytes(detail.table_bytes)],
                ['Estimated rows', detail.estimated_rows?.toLocaleString('en-IN') ?? 'not counted yet'],
                ...Object.entries(detail.stats).map(([k, v]) => [k.replace(/_/g, ' '), v === null ? '—' : typeof v === 'number' ? v.toLocaleString('en-IN') : v.replace('T', ' ').slice(0, 19)]),
              ].map(([label, value]) => (
                <div key={label} className="contents">
                  <dt className="text-[color:var(--color-text-muted)]">{label}</dt>
                  <dd className="text-[color:var(--color-text)]">{value}</dd>
                </div>
              ))}
            </dl>
          )}
          {tab === 'CREATE statement' && (
            <div className="space-y-2">
              <pre className="max-h-[22rem] overflow-auto rounded-lg border border-[color:var(--color-border)] bg-muted/40 p-3 font-mono text-xs leading-relaxed text-[color:var(--color-text)]">{detail.ddl}</pre>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" onClick={() => void copy(detail.ddl)}>
                  <ClipboardCopy className="h-4 w-4" /> {copied ? 'Copied' : 'Copy'}
                </Button>
                <Button variant="secondary" size="sm" onClick={() => onOpenSql(detail.ddl, false)}>
                  Open in the editor
                </Button>
              </div>
              <p className="text-xs text-[color:var(--color-text-muted)]">This is read from the database to look at or to copy. Orion’s own tables are changed through its schema files, not from here.</p>
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}

function List({ title, empty, items }: { title: string; empty: string; items: { key: string; head: string; body: string }[] }) {
  return (
    <section>
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[color:var(--color-text-muted)]">{title}</h3>
      {items.length === 0 ? (
        <p className="text-sm text-[color:var(--color-text-muted)]">{empty}</p>
      ) : (
        <ul className="divide-y divide-[color:var(--color-border)] rounded-lg border border-[color:var(--color-border)]">
          {items.map((item) => (
            <li key={item.key} className="px-3 py-2">
              <p className="text-sm font-medium text-[color:var(--color-text)]">{item.head}</p>
              <p className="break-words font-mono text-xs text-[color:var(--color-text-muted)]">{item.body}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
