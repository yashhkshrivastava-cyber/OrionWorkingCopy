import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, BookMarked, Braces, FilePlus2, History, PanelLeftClose, PanelLeftOpen, Play, Plus, Save, SquareStack, Table2, TextCursorInput, Timer, X } from 'lucide-react'
import type { SQLNamespace } from '@codemirror/lang-sql'
import { api } from '../../api/client'
import { ObjectDetailModal } from '../../components/sql/ObjectDetailModal'
import { SchemaTree, type PickedObject } from '../../components/sql/SchemaTree'
import { SaveQueryModal, QueryHistory, SavedQueries } from '../../components/sql/SqlSidePanels'
import { SqlCodeEditor, type SqlCodeEditorHandle } from '../../components/sql/SqlCodeEditor'
import { SqlResultGrid } from '../../components/sql/SqlResultGrid'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Field, Input, Select } from '../../components/ui/Field'
import { Modal } from '../../components/ui/Modal'
import { saveBlob } from '../../components/ui/PdfPreview'
import { useToast } from '../../components/ui/Toast'
import type { SqlCatalog, SqlRun, SqlSavedQuery, SqlStatus } from '../../types'

interface QueryTab {
  id: string
  title: string
  sql: string
  /** The saved query this tab is, when it is one. */
  savedId: number | null
  folder: string
  description: string
  shared: boolean
}

interface RunState {
  run: SqlRun | null
  running: boolean
  startedAt: number
  runId: string
  /** The script that was run, for exporting all its rows and for finding the line of an error. */
  sql: string
  view: number | 'messages'
}

interface Prefs {
  limit: number
  timeout: number
  rollback: boolean
  editorHeight: number
  panel: 'explorer' | 'saved' | 'history'
  sidebar: boolean
}

const TABS_KEY = 'orion.sql.tabs'
const PREFS_KEY = 'orion.sql.prefs'
const DEFAULT_PREFS: Prefs = { limit: 1000, timeout: 30, rollback: true, editorHeight: 260, panel: 'explorer', sidebar: true }

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback
  } catch {
    return fallback // private window, blocked storage, or a value that is not JSON: the editor still works, it just does not remember
  }
}

function write(key: string, value: unknown) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* it does not remember: nothing to do */
  }
}

let counter = 0
const newTab = (sql = '', title?: string, extra: Partial<QueryTab> = {}): QueryTab => {
  counter += 1
  return { id: `${Date.now().toString(36)}${counter}`, title: title ?? `Query ${counter}`, sql, savedId: null, folder: '', description: '', shared: false, ...extra }
}

const NAME = /^[a-z_][a-z0-9_]*$/

/**
 * The SQL editor, for administrators: the database as a tree on the left (tables, views, columns, keys), saved queries and the history of what was run,
 * and in the middle tabs of queries with an editor that completes table and column names, results in a grid with sorting and filters, the plan of a
 * query, messages, and a way to save a query as a view. By default it only reads; "Allow changes" lets it change data and make views and tables
 * (in the reports schema), after the changes are rolled back for a look if asked. Every run is kept in the history for good.
 */
export function SqlEditorPage() {
  const toast = useToast()
  const [status, setStatus] = useState<SqlStatus | null>(null)
  const [catalog, setCatalog] = useState<SqlCatalog | null>(null)
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [error, setError] = useState('')
  const [prefs, setPrefs] = useState<Prefs>(() => read(PREFS_KEY, DEFAULT_PREFS))
  const [tabs, setTabs] = useState<QueryTab[]>(() => {
    const saved = read<{ tabs: QueryTab[]; active: string }>(TABS_KEY, { tabs: [], active: '' })
    return saved.tabs.length ? saved.tabs : [newTab('SELECT *\nFROM orion_ods.client\nLIMIT 100;')]
  })
  const [activeId, setActiveId] = useState(() => {
    const saved = read<{ tabs: QueryTab[]; active: string }>(TABS_KEY, { tabs: [], active: '' })
    return saved.tabs.some((t) => t.id === saved.active) ? saved.active : (saved.tabs[0]?.id ?? '')
  })
  const [runs, setRuns] = useState<Record<string, RunState>>({})
  const [allowChanges, setAllowChanges] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [describe, setDescribe] = useState<{ schema: string; name: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [viewing, setViewing] = useState(false)
  const [viewName, setViewName] = useState('')
  const [viewKind, setViewKind] = useState<'view' | 'materialized view' | 'table'>('view')
  const [reload, setReload] = useState(0)
  const editor = useRef<SqlCodeEditorHandle>(null)
  const split = useRef<HTMLDivElement>(null)

  const active = tabs.find((t) => t.id === activeId) ?? tabs[0]
  const state = runs[active.id]

  useEffect(() => write(PREFS_KEY, prefs), [prefs])
  useEffect(() => write(TABS_KEY, { tabs, active: active.id }), [tabs, active.id])

  const loadCatalog = useCallback(() => {
    setCatalogLoading(true)
    api
      .sqlCatalog()
      .then(setCatalog)
      .catch((e: Error) => setError(e.message))
      .finally(() => setCatalogLoading(false))
  }, [])
  useEffect(() => {
    api.sqlStatus().then(setStatus).catch((e: Error) => setError(e.message))
    loadCatalog()
  }, [loadCatalog])

  // The tables and columns the editor completes.
  const schema: SQLNamespace = useMemo(() => {
    const out: Record<string, Record<string, string[]>> = {}
    for (const s of catalog?.schemas ?? []) {
      out[s.name] = {}
      for (const o of s.objects) if (!o.private) out[s.name][o.name] = o.columns.map((c) => c.name)
    }
    return out
  }, [catalog])

  // While a run is going, the clock shows how long.
  useEffect(() => {
    if (!state?.running) return
    const timer = window.setInterval(() => setElapsed(Date.now() - state.startedAt), 200)
    return () => window.clearInterval(timer)
  }, [state?.running, state?.startedAt])

  const patchTab = (id: string, patch: Partial<QueryTab>) => setTabs((now) => now.map((t) => (t.id === id ? { ...t, ...patch } : t)))
  const patchRun = (id: string, patch: Partial<RunState>) => setRuns((now) => ({ ...now, [id]: { ...(now[id] ?? { run: null, running: false, startedAt: 0, runId: '', sql: '', view: 0 }), ...patch } }))

  const openTab = (sql: string, title?: string, extra: Partial<QueryTab> = {}) => {
    const tab = newTab(sql, title, extra)
    setTabs((now) => [...now, tab])
    setActiveId(tab.id)
    return tab
  }

  const closeTab = (id: string) => {
    if (tabs.length === 1) {
      const fresh = newTab('')
      setTabs([fresh])
      setActiveId(fresh.id)
      return
    }
    const index = tabs.findIndex((t) => t.id === id)
    const next = tabs.filter((t) => t.id !== id)
    setTabs(next)
    if (id === activeId) setActiveId(next[Math.max(0, index - 1)].id)
  }

  // --- running -----------------------------------------------------------------------------------------------------------
  const execute = async (text: string, confirm = false) => {
    const tabId = active.id
    if (!text.trim()) {
      toast.show('There is nothing to run. Write a query first.')
      return
    }
    const runId = crypto.randomUUID()
    patchRun(tabId, { running: true, startedAt: Date.now(), runId, sql: text, run: confirm ? runs[tabId]?.run ?? null : null, view: 0 })
    setElapsed(0)
    try {
      const run = await api.sqlRun({ sql: text, write: allowChanges, rollback: prefs.rollback, limit: prefs.limit, timeout: prefs.timeout, run_id: runId, confirm })
      if (run.needs_confirmation) {
        patchRun(tabId, { running: false })
        if (window.confirm(`${run.needs_confirmation.join('\n\n')}\n\n${prefs.rollback ? 'It will be rolled back, so you can see what it would do.' : 'It will be committed.'}\n\nRun it?`)) await execute(text, true)
        return
      }
      patchRun(tabId, { run, running: false, view: run.ok && run.results.length ? 0 : 'messages' })
      setReload((n) => n + 1)
      if (run.changed) {
        toast.show('The changes were saved to the database.')
        loadCatalog()
      }
    } catch (e) {
      patchRun(tabId, { running: false, run: { ok: false, results: [], run_id: runId, error: { message: (e as Error).message, hint: null, detail: null, code: null, position: null } }, view: 'messages' })
    }
  }

  const run = (mode: 'all' | 'statement') => {
    const handle = editor.current
    if (!handle) return
    const selection = handle.getSelection()
    const text = selection || (mode === 'statement' ? handle.getStatementAtCursor() : handle.getText())
    void execute(text)
  }

  const cancel = async () => {
    if (!state?.runId) return
    try {
      await api.sqlCancel(state.runId)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const explain = (analyze: boolean) => {
    const handle = editor.current
    const text = (handle?.getSelection() || handle?.getStatementAtCursor() || '').replace(/;\s*$/, '')
    if (!text.trim()) {
      toast.show('Put the cursor in a query to explain it.')
      return
    }
    void execute(`EXPLAIN ${analyze ? '(ANALYZE, BUFFERS) ' : ''}${text}`)
  }

  const format = async () => {
    const handle = editor.current
    if (!handle) return
    const { format: pretty } = await import('sql-formatter')
    try {
      const text = handle.getText()
      handle.setText(pretty(text, { language: 'postgresql', keywordCase: 'upper', tabWidth: 4 }))
    } catch (e) {
      toast.show(`It could not be formatted: ${(e as Error).message.split('\n')[0]}`)
    }
  }

  const exportAll = async () => {
    if (!state?.sql) return
    try {
      saveBlob(await api.sqlExport(state.sql), `query-${new Date().toISOString().slice(0, 10)}.csv`)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // --- saving ---------------------------------------------------------------------------------------------------------------
  const saveQuery = async (values: { title: string; folder: string; description: string; shared: boolean; asCopy: boolean }) => {
    const text = editor.current?.getText() ?? active.sql
    const id = values.asCopy ? null : active.savedId
    const made = await api.sqlSave(id, { title: values.title, sql: text, folder: values.folder || null, description: values.description || null, shared: values.shared })
    patchTab(active.id, { savedId: made.id, title: values.title, folder: values.folder, description: values.description, shared: values.shared, sql: text })
    setSaving(false)
    setReload((n) => n + 1)
    toast.show('Saved.')
  }

  const openSaved = (query: SqlSavedQuery) => {
    const open = tabs.find((t) => t.savedId === query.id)
    if (open) return setActiveId(open.id)
    openTab(query.sql, query.title, { savedId: query.mine ? query.id : null, folder: query.folder ?? '', description: query.description ?? '', shared: query.shared })
  }

  const makeView = () => {
    const handle = editor.current
    const body = (handle?.getSelection() || handle?.getStatementAtCursor() || handle?.getText() || '').replace(/;\s*$/, '').trim()
    if (!body) return toast.show('Write the query that the view should hold first.')
    if (!NAME.test(viewName)) return setError('Name it with lower-case letters, digits and underscores, for example open_bills.')
    const reports = status?.reports_schema ?? 'reports'
    const head = viewKind === 'table' ? `CREATE TABLE ${reports}.${viewName} AS` : viewKind === 'materialized view' ? `CREATE MATERIALIZED VIEW ${reports}.${viewName} AS` : `CREATE OR REPLACE VIEW ${reports}.${viewName} AS`
    openTab(`${head}\n${body};`, `Create ${viewName}`)
    setViewing(false)
    setViewName('')
    toast.show(allowChanges ? 'Review it, then run it.' : 'Turn on “Allow changes” to run it. It makes the object in the reports schema.')
  }

  // --- the split between the editor and the results ------------------------------------------------------------------------
  const drag = (event: React.PointerEvent) => {
    const box = split.current
    if (!box) return
    const top = box.getBoundingClientRect().top
    const move = (e: PointerEvent) => setPrefs((p) => ({ ...p, editorHeight: Math.max(110, Math.min(box.clientHeight - 140, e.clientY - top)) }))
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    event.preventDefault()
  }

  const turnChanges = (on: boolean) => {
    if (on && !window.confirm('Allow this editor to change the database?\n\nChanges can be rolled back for a look first (the box beside it). Orion’s own records (bills, the bank, documents and the like) can be read here but are changed only through the application. Every run is recorded.')) return
    setAllowChanges(on)
  }

  const result = state?.run
  const sets = result?.results ?? []
  const view = state?.view ?? 0
  const shown = typeof view === 'number' ? sets[view] : undefined
  const reportsHint = status?.reports_schema ?? 'reports'
  const panelButton = (id: Prefs['panel'], label: string, Icon: typeof Table2) => (
    <button key={id} type="button" role="tab" aria-selected={prefs.panel === id} onClick={() => setPrefs((p) => ({ ...p, panel: id }))} className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-medium ${prefs.panel === id ? 'bg-accent-dim text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:bg-muted'}`}>
      <Icon className="h-3.5 w-3.5" /> {label}
    </button>
  )

  if (status && status.mode === 'off') {
    return <Alert variant="info">The SQL editor is switched off on this server.</Alert>
  }

  return (
    <div className="flex h-[calc(100dvh-6.25rem)] min-h-[34rem] gap-3">
      {prefs.sidebar && (
        <aside className="panel hidden w-72 shrink-0 flex-col p-2 md:flex" aria-label="Database, saved queries and history">
          <div className="mb-2 flex gap-1" role="tablist">
            {panelButton('explorer', 'Database', Table2)}
            {panelButton('saved', 'Saved', BookMarked)}
            {panelButton('history', 'History', History)}
          </div>
          <div className="min-h-0 flex-1">
            {prefs.panel === 'explorer' && (
              <SchemaTree
                catalog={catalog}
                loading={catalogLoading}
                onRefresh={loadCatalog}
                onInsert={(text) => editor.current?.insert(text)}
                onQuery={(sql, go) => {
                  const tab = openTab(sql)
                  if (go) window.setTimeout(() => void execute(tab.sql), 50)
                }}
                onDescribe={(picked: PickedObject) => setDescribe({ schema: picked.schema, name: picked.object.name })}
              />
            )}
            {prefs.panel === 'saved' && <SavedQueries reload={reload} onOpen={openSaved} onEdit={(q) => { openSaved(q); setSaving(true) }} />}
            {prefs.panel === 'history' && <QueryHistory reload={reload} onOpen={(sql) => openTab(sql)} />}
          </div>
        </aside>
      )}

      <section className="flex min-w-0 flex-1 flex-col gap-2">
        {error && (
          <Alert variant="error" onDismiss={() => setError('')}>
            {error}
          </Alert>
        )}

        {/* The tools. */}
        <div className={`panel flex flex-wrap items-center gap-2 px-2 py-1.5 ${allowChanges ? 'border-warning/60' : ''}`}>
          <Button variant="ghost" size="sm" className="hidden md:inline-flex" onClick={() => setPrefs((p) => ({ ...p, sidebar: !p.sidebar }))} aria-label={prefs.sidebar ? 'Hide the side panel' : 'Show the side panel'} title={prefs.sidebar ? 'Hide the side panel' : 'Show the side panel'}>
            {prefs.sidebar ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
          </Button>
          {state?.running ? (
            <Button variant="danger" size="sm" onClick={() => void cancel()}>
              <X className="h-4 w-4" /> Cancel · {(elapsed / 1000).toFixed(1)} s
            </Button>
          ) : (
            <Button size="sm" onClick={() => run('all')} title="Run the selection, or everything (Ctrl+Enter)">
              <Play className="h-4 w-4" /> Run
            </Button>
          )}
          <Button variant="secondary" size="sm" disabled={state?.running} onClick={() => run('statement')} title="Run the selection, or the statement the cursor is in (Ctrl+Shift+Enter)">
            <TextCursorInput className="h-4 w-4" /> <span className="hidden lg:inline">Run statement</span>
          </Button>
          <span className="mx-1 hidden h-5 w-px bg-[color:var(--color-border)] sm:block" />
          <Button variant="ghost" size="sm" disabled={state?.running} onClick={() => explain(false)} title="Show how the database would run this statement">
            Explain
          </Button>
          <Button variant="ghost" size="sm" disabled={state?.running} onClick={() => explain(true)} title="Run the statement and show where its time went">
            Analyze
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void format()} title="Tidy the SQL (Ctrl+Shift+F)">
            <Braces className="h-4 w-4" /> <span className="hidden lg:inline">Format</span>
          </Button>
          <span className="mx-1 hidden h-5 w-px bg-[color:var(--color-border)] sm:block" />
          <Button variant="ghost" size="sm" onClick={() => setSaving(true)} title="Save this query (Ctrl+S)">
            <Save className="h-4 w-4" /> <span className="hidden lg:inline">Save</span>
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setViewing(true)} title="Keep this query as a view, or copy its rows into a table, in the reports schema">
            <SquareStack className="h-4 w-4" /> <span className="hidden lg:inline">Save as view</span>
          </Button>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1 text-xs text-[color:var(--color-text-muted)]" title="The most rows a query shows">
              Rows
              <Select aria-label="Most rows to show" className="!min-h-0 !w-auto !py-1 text-xs" value={prefs.limit} onChange={(e) => setPrefs((p) => ({ ...p, limit: Number(e.target.value) }))}>
                {[100, 500, 1000, 5000, status?.max_limit ?? 10000].filter((v, i, a) => a.indexOf(v) === i).map((v) => (
                  <option key={v} value={v}>
                    {v.toLocaleString('en-IN')}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex items-center gap-1 text-xs text-[color:var(--color-text-muted)]" title="A query is stopped after this long">
              <Timer className="h-3.5 w-3.5" />
              <Select aria-label="Time limit" className="!min-h-0 !w-auto !py-1 text-xs" value={prefs.timeout} onChange={(e) => setPrefs((p) => ({ ...p, timeout: Number(e.target.value) }))}>
                {[10, 30, 60, status?.max_timeout ?? 120].filter((v, i, a) => a.indexOf(v) === i).map((v) => (
                  <option key={v} value={v}>
                    {v} s
                  </option>
                ))}
              </Select>
            </label>
            {status?.can_change ? (
              <div className={`flex items-center gap-2 rounded-lg px-2 py-1 ${allowChanges ? 'bg-warning-dim' : ''}`}>
                <label className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-[color:var(--color-text)]">
                  <input type="checkbox" checked={allowChanges} onChange={(e) => turnChanges(e.target.checked)} /> Allow changes
                </label>
                {allowChanges && (
                  <label className="flex cursor-pointer items-center gap-1.5 text-xs text-[color:var(--color-text)]" title="Run it, show what it did, then undo it">
                    <input type="checkbox" checked={prefs.rollback} onChange={(e) => setPrefs((p) => ({ ...p, rollback: e.target.checked }))} /> Roll back after running
                  </label>
                )}
              </div>
            ) : (
              status && <span className="text-xs text-[color:var(--color-text-muted)]" title="Switched on in this server's .env with ORION_SQL_EDITOR=full">Read only on this server</span>
            )}
          </div>
        </div>

        {allowChanges && (
          <p className="flex items-center gap-2 rounded-lg bg-warning-dim px-3 py-1.5 text-xs text-[color:var(--color-text)]" role="status">
            <AlertTriangle className="h-4 w-4 shrink-0 text-warning" />
            Changes are allowed. {prefs.rollback ? 'They are rolled back after each run, so you can look first.' : 'What you run is saved to the database.'} Orion’s own records are read-only here; views and tables go in the {reportsHint} schema.
          </p>
        )}

        {/* Tabs of queries. */}
        <div className="scroll-quiet flex items-center gap-1 overflow-x-auto" role="tablist" aria-label="Queries">
          {tabs.map((tab) => (
            <div key={tab.id} className={`group flex shrink-0 items-center rounded-lg border text-sm ${tab.id === active.id ? 'border-accent bg-accent-dim text-[color:var(--color-text)]' : 'border-[color:var(--color-border)] text-[color:var(--color-text-muted)] hover:bg-muted'}`}>
              <button type="button" role="tab" aria-selected={tab.id === active.id} onClick={() => setActiveId(tab.id)} onDoubleClick={() => { const name = window.prompt('Name this tab', tab.title); if (name?.trim()) patchTab(tab.id, { title: name.trim().slice(0, 60) }) }} className="max-w-[12rem] truncate px-3 py-1.5" title={`${tab.title} (double-click to rename)`}>
                {runs[tab.id]?.running && <span className="mr-1.5 inline-block h-2 w-2 animate-pulse rounded-full bg-accent" aria-label="running" />}
                {tab.title}
              </button>
              <button type="button" onClick={() => closeTab(tab.id)} aria-label={`Close ${tab.title}`} className="rounded p-1 pr-1.5 text-[color:var(--color-text-faint)] hover:text-[color:var(--color-text)]">
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
          <Button variant="ghost" size="sm" onClick={() => openTab('')} aria-label="New query" title="A new query tab">
            <Plus className="h-4 w-4" />
          </Button>
        </div>

        {/* The editor over the results. */}
        <div ref={split} className="flex min-h-0 flex-1 flex-col">
          <div className="panel overflow-hidden" style={{ height: prefs.editorHeight }}>
            <SqlCodeEditor
              ref={editor}
              tabKey={active.id}
              initial={active.sql}
              schema={schema}
              onChange={(text) => patchTab(active.id, { sql: text })}
              onRun={run}
              onSave={() => setSaving(true)}
              onFormat={() => void format()}
            />
          </div>
          <div role="separator" aria-orientation="horizontal" aria-label="Resize the editor" tabIndex={0} onPointerDown={drag} onKeyDown={(e) => { if (e.key === 'ArrowUp') setPrefs((p) => ({ ...p, editorHeight: Math.max(110, p.editorHeight - 30) })); if (e.key === 'ArrowDown') setPrefs((p) => ({ ...p, editorHeight: p.editorHeight + 30 })) }} className="group flex h-3 shrink-0 cursor-row-resize items-center justify-center focus-visible:outline-none">
            <span className="h-1 w-12 rounded-full bg-[color:var(--color-border-strong)] group-hover:bg-accent" />
          </div>
          <div className="panel flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="flex items-center gap-1 border-b border-[color:var(--color-border)] px-2 py-1" role="tablist" aria-label="Results">
              {sets.map((set, index) => (
                <button key={set.index} type="button" role="tab" aria-selected={view === index} onClick={() => patchRun(active.id, { view: index })} className={`rounded-md px-2.5 py-1 text-xs ${view === index ? 'bg-accent-dim font-semibold text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:bg-muted'}`}>
                  {set.kind === 'rows' ? `Result ${set.index} · ${set.row_count.toLocaleString('en-IN')}${set.truncated ? '+' : ''}` : `${set.command}`}
                </button>
              ))}
              <button type="button" role="tab" aria-selected={view === 'messages'} onClick={() => patchRun(active.id, { view: 'messages' })} className={`rounded-md px-2.5 py-1 text-xs ${view === 'messages' ? 'bg-accent-dim font-semibold text-[color:var(--color-text)]' : 'text-[color:var(--color-text-muted)] hover:bg-muted'}`}>
                Messages{result && !result.ok ? ' ●' : ''}
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto">
              {!result && !state?.running && (
                <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-sm text-[color:var(--color-text-muted)]">
                  <FilePlus2 className="h-6 w-6 text-accent" aria-hidden="true" />
                  <p>Write a query and press Run (Ctrl+Enter). Right-click a table on the left for the usual queries.</p>
                </div>
              )}
              {state?.running && <p className="p-4 text-sm text-[color:var(--color-text-muted)]">Running… {(elapsed / 1000).toFixed(1)} s</p>}
              {!state?.running && result && view === 'messages' && (
                <Messages run={result} onGoTo={(line, column) => editor.current?.goTo(line, column)} />
              )}
              {!state?.running && shown && shown.kind === 'rows' && <SqlResultGrid key={`${active.id}-${shown.index}-${state?.runId}`} result={shown} onExportAll={() => void exportAll()} />}
              {!state?.running && shown && shown.kind === 'command' && (
                <p className="p-4 text-sm text-[color:var(--color-text)]">
                  {shown.command}
                  <span className="text-[color:var(--color-text-muted)]"> · {shown.duration_ms} ms</span>
                </p>
              )}
            </div>
          </div>
        </div>

        <footer className="flex flex-wrap items-center gap-x-4 gap-y-0.5 px-1 text-[11px] text-[color:var(--color-text-faint)]">
          <span>
            {status ? `${status.database} as ${status.role} · PostgreSQL ${status.version}` : 'Connecting…'}
          </span>
          <span>{allowChanges ? 'changes allowed' : 'read only'}</span>
          {result && (
            <span>
              {result.ok ? 'Ran' : 'Stopped'} in {result.duration_ms ?? 0} ms{result.rolled_back ? ' · changes rolled back' : ''}
              {sets.length ? ` · ${sets.reduce((n, s) => n + s.row_count, 0).toLocaleString('en-IN')} rows` : ''}
            </span>
          )}
          <span className="ml-auto">Every run is recorded in the history.</span>
        </footer>
      </section>

      <ObjectDetailModal target={describe} onClose={() => setDescribe(null)} onOpenSql={(sql, go) => { setDescribe(null); const tab = openTab(sql); if (go) window.setTimeout(() => void execute(tab.sql), 50) }} />

      <SaveQueryModal
        open={saving}
        initial={{ title: active.savedId ? active.title : '', folder: active.folder, description: active.description, shared: active.shared, isNew: active.savedId === null }}
        onClose={() => setSaving(false)}
        onSave={saveQuery}
      />

      <Modal
        open={viewing}
        title="Save this query as a view"
        onClose={() => setViewing(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setViewing(false)}>
              Cancel
            </Button>
            <Button onClick={makeView} disabled={!viewName}>
              Write the CREATE statement
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm">
          <p className="text-[color:var(--color-text-muted)]">
            A view keeps the query under a name, so it can be read like a table (for example by a spreadsheet or another query). It is made in the <strong>{reportsHint}</strong> schema, which is yours to
            change; Orion’s own tables are never altered from here. The statement opens in a new tab for you to look at and run.
          </p>
          <Field label="Name" hint="Lower-case letters, digits and underscores, for example open_bills.">
            <div className="flex items-center gap-1">
              <span className="text-[color:var(--color-text-muted)]">{reportsHint}.</span>
              <Input autoFocus value={viewName} maxLength={60} onChange={(e) => setViewName(e.target.value.toLowerCase())} />
            </div>
          </Field>
          <Field label="Make it">
            <Select value={viewKind} onChange={(e) => setViewKind(e.target.value as typeof viewKind)}>
              <option value="view">A view (always shows the current data)</option>
              <option value="materialized view">A materialized view (a stored copy, refreshed when you ask)</option>
              <option value="table">A table (a copy of the rows as they are now)</option>
            </Select>
          </Field>
          {!status?.can_change && <Alert variant="info">Changes are switched off on this server, so this cannot be run here.</Alert>}
        </div>
      </Modal>
    </div>
  )
}

/** What happened, statement by statement: what ran, how long it took, what it did, and where an error is. */
function Messages({ run, onGoTo }: { run: SqlRun; onGoTo: (line: number, column?: number) => void }) {
  return (
    <div className="space-y-2 p-3 text-sm">
      {run.blocked && <Alert variant="warning">Nothing was run. {run.error?.message}</Alert>}
      {run.error && !run.blocked && (
        <Alert variant="error">
          <p className="font-medium">{run.error.message}</p>
          {run.error.detail && <p className="mt-1 text-xs">{run.error.detail}</p>}
          {run.error.hint && <p className="mt-1 text-xs">Hint: {run.error.hint}</p>}
          {run.error.position && (
            <button type="button" className="mt-1 text-xs font-medium underline" onClick={() => onGoTo(run.error!.position!.line, run.error!.position!.column)}>
              Go to line {run.error.position.line}, column {run.error.position.column}
            </button>
          )}
          {run.rolled_back && <p className="mt-1 text-xs">Nothing from this run was kept.</p>}
        </Alert>
      )}
      {run.results.map((set) => (
        <p key={set.index} className="font-mono text-xs text-[color:var(--color-text)]">
          <span className="text-[color:var(--color-text-faint)]">{set.index}.</span> {set.command}
          {set.kind === 'rows' ? ` · ${set.row_count.toLocaleString('en-IN')} rows${set.truncated ? ' (more than the limit)' : ''}` : ''} · {set.duration_ms} ms
          <span className="block truncate text-[color:var(--color-text-muted)]">{set.statement.replace(/\s+/g, ' ')}</span>
        </p>
      ))}
      {run.ok && run.rolled_back && (
        <Alert variant="info">The changes were run and then rolled back, so you could see what they do. Untick “Roll back after running” to keep them.</Alert>
      )}
      {run.ok && run.changed && <Alert variant="success">The changes were saved to the database.</Alert>}
      {run.ok && !run.results.length && <p className="text-[color:var(--color-text-muted)]">Nothing to show.</p>}
    </div>
  )
}
