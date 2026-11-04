import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FilePlus2, Search } from 'lucide-react'
import { api } from '../../api/client'
import { ReportTable } from '../../components/dashboard/ReportTable'
import { formatDay } from '../../components/billing/BillDocument'
import { LetterCard, PdfCard, StartCard } from '../../components/letterhead/lumenLetters'
import { TEMPLATES } from '../../components/letterhead/templates'
import { Alert } from '../../components/ui/Alert'
import { useAuth } from '../../context/AuthContext'
import { useDataRefresh } from '../../context/DataRefreshContext'
import { useLumen } from '../../lumen/useLumen'
import type { LetterSummary, TableBlock } from '../../types'

/** Every letter written on the letterhead, newest first, and the ways to start a new one. */
export function LettersPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const { generation } = useDataRefresh()
  const lumen = useLumen()
  const canWrite = Boolean(user?.can_letterhead_write)
  const [find, setFind] = useState('')
  const [shown, setShown] = useState(12)
  const [letters, setLetters] = useState<LetterSummary[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .letters()
      .then((r) => setLetters(r.letters))
      .catch((e: Error) => setError(e.message))
  }, [generation])

  const table: TableBlock = useMemo(
    () => ({
      filter_key: null,
      columns: [
        { key: 'letter_date', label: 'Date', format: 'text', align: 'left' },
        { key: 'title', label: 'Name', format: 'text', align: 'left' },
        { key: 'ref_no', label: 'Ref. no.', format: 'text', align: 'left' },
        { key: 'preview', label: 'Begins', format: 'text', align: 'left' },
        { key: 'changed', label: 'Last changed', format: 'text', align: 'left' },
        { key: 'changed_by', label: 'By', format: 'text', align: 'left' },
      ],
      rows: (letters ?? []).map((letter) => ({
        code: String(letter.letter_id),
        letter_date: formatDay(letter.letter_date),
        letter_date_sort: letter.letter_date,
        title: letter.title,
        ref_no: letter.ref_no ?? '',
        preview: letter.preview,
        changed: formatDay(letter.last_updated_timestamp),
        changed_sort: letter.last_updated_timestamp,
        changed_by: letter.last_updated_by_name ?? letter.created_by_name ?? '',
      })),
      truncated: (letters?.length ?? 0) >= 500,
    }),
    [letters],
  )

  const found = useMemo(() => {
    const needle = find.trim().toLowerCase()
    return (letters ?? []).filter((l) => !needle || [l.title, l.ref_no, l.preview].some((text) => (text ?? '').toLowerCase().includes(needle)))
  }, [letters, find])

  if (lumen) {
    return (
      <div className="space-y-6">
        <div>
          <h2 className="t-h2">What do you want to write?</h2>
          <p className="t-small mt-1 max-w-2xl text-[color:var(--color-text-muted)]">Choose one and it opens on the company letterhead. Print it or save it as a PDF; everything you write is kept here.</p>
        </div>
        {error && <Alert variant="error">{error}</Alert>}
        {canWrite && (
          <section aria-label="Start a new document" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {TEMPLATES.map((template) => (
              <StartCard key={template.id} id={template.id} label={template.label} hint={template.hint} onClick={() => navigate(`/letterhead/letters/new?template=${template.id}`)} />
            ))}
            <PdfCard onClick={() => navigate('/letterhead/pdf')} />
          </section>
        )}
        <section aria-label="Saved letters" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="t-h3">Saved letters</h3>
            {letters && letters.length > 0 && (
              <label className="relative block w-full sm:w-72">
                <span className="sr-only">Search the letters</span>
                <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
                <input value={find} onChange={(e) => { setFind(e.target.value); setShown(12) }} placeholder="Search name, ref. no. or text" className="h-11 w-full rounded-full pr-4 text-sm" style={{ paddingLeft: '2.75rem' }} />
              </label>
            )}
          </div>
          {letters === null ? (
            <div className="shimmer h-40 rounded-2xl bg-muted" aria-busy="true" />
          ) : letters.length === 0 ? (
            <div className="panel px-6 py-12 text-center">
              <p className="font-display text-lg font-semibold">No letters yet</p>
              <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">{canWrite ? 'Choose what to write above.' : 'Letters written by your team will appear here.'}</p>
            </div>
          ) : found.length === 0 ? (
            <p className="panel px-6 py-10 text-center text-sm text-[color:var(--color-text-muted)]">No letter matches that.</p>
          ) : (
            <>
              <ul className="space-y-2.5">
                {found.slice(0, shown).map((letter) => (
                  <LetterCard key={letter.letter_id} letter={letter} onOpen={() => navigate(`/letterhead/letters/${letter.letter_id}`)} />
                ))}
              </ul>
              {found.length > shown && (
                <div className="flex justify-center">
                  <button type="button" onClick={() => setShown((n) => n + 12)} className="interactive rounded-full border border-[color:var(--color-border)] px-5 py-2 text-sm font-semibold text-[color:var(--color-text-muted)] hover:bg-muted">
                    Show {Math.min(12, found.length - shown)} more
                  </button>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-[color:var(--color-text)]">Letters</h2>
        <p className="text-sm text-[color:var(--color-text-muted)]">
          Type a letter, quotation, notice or certificate straight onto the company letterhead, then print it or
          save it as a PDF. Everything written here is kept and can be opened again.
        </p>
      </div>

      {error && <Alert variant="error">{error}</Alert>}

      {canWrite && (
        <section aria-label="Start a new document" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {TEMPLATES.map((template) => (
            <button
              key={template.id}
              type="button"
              onClick={() => navigate(`/letterhead/letters/new?template=${template.id}`)}
              className="interactive group rounded-xl border border-[color:var(--color-border)] bg-surface px-4 py-3 text-left shadow-card hover:border-[color:var(--color-accent)] focus-visible:ring-2 focus-visible:ring-accent"
            >
              <span className="flex items-center gap-2 text-sm font-semibold text-[color:var(--color-text)]">
                <FilePlus2 className="h-4 w-4 text-accent" aria-hidden="true" />
                New {template.label.toLowerCase()}
              </span>
              <span className="mt-1 block text-xs text-[color:var(--color-text-muted)]">{template.hint}</span>
            </button>
          ))}
        </section>
      )}

      <section className="rounded-xl border border-[color:var(--color-border)] bg-surface">
        <header className="border-b border-[color:var(--color-border)] px-4 py-3">
          <h3 className="text-sm font-semibold text-[color:var(--color-text)]">Saved letters</h3>
        </header>
        <div className="py-3">
          {letters === null ? (
            <div className="shimmer mx-4 h-40 rounded-lg bg-muted" aria-busy="true" />
          ) : letters.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <p className="text-sm font-medium text-[color:var(--color-text)]">No letters yet</p>
              <p className="mt-1 text-sm text-[color:var(--color-text-muted)]">
                {canWrite ? 'Choose what to start from above.' : 'Letters written by your team will appear here.'}
              </p>
            </div>
          ) : (
            <ReportTable
              block={table}
              exportName="letters"
              onOpen={(id) => navigate(`/letterhead/letters/${id}`)}
              searchLabel="Search name, ref. no. or text"
              defaultSort={{ key: 'letter_date', dir: 'desc' }}
              emptyMessage="No letters."
              pageSize={25}
            />
          )}
        </div>
      </section>
    </div>
  )
}
