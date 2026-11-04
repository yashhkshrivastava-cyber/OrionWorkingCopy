import { useMemo, useState } from 'react'
import { ChevronRight, Database, Eye, KeyRound, Link2, Lock, RefreshCw, Table2 } from 'lucide-react'
import type { SqlCatalog, SqlObject } from '../../types'
import { ContextMenu, type MenuItem } from '../documents/explorerUi'
import { Input } from '../ui/Field'

export interface PickedObject {
  schema: string
  object: SqlObject
}

const quoteName = (name: string) => (/^[a-z_][a-z0-9_]*$/.test(name) ? name : `"${name.replace(/"/g, '""')}"`)
export const qualified = (schema: string, name: string) => `${quoteName(schema)}.${quoteName(name)}`

/** The size of a table in words people read: 12 KB, 3.4 MB. */
export function bytes(value: number): string {
  if (value >= 1024 ** 3) return `${(value / 1024 ** 3).toFixed(1)} GB`
  if (value >= 1024 ** 2) return `${(value / 1024 ** 2).toFixed(1)} MB`
  return `${Math.max(1, Math.round(value / 1024))} KB`
}

/**
 * The database as a tree, like the Object Explorer of SSMS or pgAdmin: each schema, its tables and views, and under each its columns (with keys and types).
 * Search finds tables and columns. Double-click puts a name in the editor; the right-click menu writes the usual queries, shows the structure and copies names.
 */
export function SchemaTree({
  catalog,
  loading,
  onRefresh,
  onInsert,
  onQuery,
  onDescribe,
}: {
  catalog: SqlCatalog | null
  loading: boolean
  onRefresh: () => void
  onInsert: (text: string) => void
  onQuery: (sql: string, run: boolean) => void
  onDescribe: (picked: PickedObject) => void
}) {
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState<Set<string>>(() => new Set(['orion_ods']))
  const [menu, setMenu] = useState<{ x: number; y: number; items: MenuItem[] } | null>(null)

  const needle = search.trim().toLowerCase()
  const schemas = useMemo(() => {
    if (!catalog) return []
    return catalog.schemas
      .map((schema) => ({
        ...schema,
        objects: schema.objects.filter((o) => !needle || o.name.toLowerCase().includes(needle) || o.columns.some((c) => c.name.toLowerCase().includes(needle))),
      }))
      .filter((schema) => !needle || schema.objects.length > 0)
  }, [catalog, needle])

  const toggle = (key: string) =>
    setOpen((now) => {
      const next = new Set(now)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const objectMenu = (schema: string, object: SqlObject): MenuItem[] => {
    const name = qualified(schema, object.name)
    const columns = object.columns.map((c) => quoteName(c.name))
    return [
      { label: 'Select top 100 rows', onClick: () => onQuery(`SELECT *\nFROM ${name}\nLIMIT 100;`, true), disabled: object.private },
      { label: 'Select with every column named', onClick: () => onQuery(`SELECT\n    ${columns.join(',\n    ')}\nFROM ${name}\nLIMIT 100;`, false), disabled: object.private },
      { label: 'Count the rows', onClick: () => onQuery(`SELECT COUNT(*) AS rows\nFROM ${name};`, true), disabled: object.private },
      { label: 'Structure, keys, indexes and CREATE statement', divider: true, onClick: () => onDescribe({ schema, object }), disabled: object.private },
      ...(object.kind === 'table'
        ? [
            { label: 'Write an INSERT', onClick: () => onQuery(`INSERT INTO ${name} (${columns.join(', ')})\nVALUES (${columns.map(() => '…').join(', ')});`, false), divider: true },
            { label: 'Write an UPDATE', onClick: () => onQuery(`UPDATE ${name}\nSET ${columns.slice(0, 2).map((c) => `${c} = …`).join(', ')}\nWHERE …;`, false) },
          ]
        : []),
      { label: 'Put the name in the editor', divider: true, onClick: () => onInsert(name) },
      { label: 'Copy the name', onClick: () => void navigator.clipboard?.writeText(name) },
    ]
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-1.5 px-2 pb-2">
        <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a table or column" aria-label="Find a table or column" className="!min-h-0 !py-1.5 text-xs" />
        <button type="button" onClick={onRefresh} aria-label="Read the database again" title="Read the database again" className="rounded-lg p-2 text-[color:var(--color-text-muted)] hover:bg-muted">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>
      <div className="scroll-quiet min-h-0 flex-1 overflow-y-auto px-1 pb-2 text-[13px]" role="tree" aria-label="Database objects">
        {!catalog && <p className="px-3 py-2 text-xs text-[color:var(--color-text-muted)]">{loading ? 'Reading the database…' : 'The database could not be read.'}</p>}
        {schemas.map((schema) => {
          const schemaOpen = open.has(schema.name) || Boolean(needle)
          return (
            <div key={schema.name} role="none">
              <button type="button" role="treeitem" aria-expanded={schemaOpen} onClick={() => toggle(schema.name)} className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left font-medium text-[color:var(--color-text)] hover:bg-muted">
                <ChevronRight className={`h-3.5 w-3.5 shrink-0 transition-transform ${schemaOpen ? 'rotate-90' : ''}`} />
                <Database className="h-3.5 w-3.5 shrink-0 text-accent" />
                <span className="min-w-0 flex-1 truncate">{schema.name}</span>
                <span className="text-[11px] tabular-nums text-[color:var(--color-text-faint)]">{schema.objects.length}</span>
              </button>
              {schemaOpen &&
                schema.objects.map((object) => {
                  const key = `${schema.name}.${object.name}`
                  const objectOpen = open.has(key) || Boolean(needle && object.columns.some((c) => c.name.toLowerCase().includes(needle)) && !object.name.toLowerCase().includes(needle))
                  const Icon = object.private ? Lock : object.kind === 'table' ? Table2 : Eye
                  return (
                    <div key={key} role="none" className="ml-3">
                      <div
                        className="group flex items-center rounded-md hover:bg-muted"
                        onContextMenu={(event) => {
                          event.preventDefault()
                          setMenu({ x: event.clientX, y: event.clientY, items: objectMenu(schema.name, object) })
                        }}
                      >
                        <button type="button" tabIndex={-1} aria-label={objectOpen ? `Close ${object.name}` : `Open ${object.name}`} onClick={() => toggle(key)} className="px-1 py-1 text-[color:var(--color-text-faint)]">
                          <ChevronRight className={`h-3 w-3 transition-transform ${objectOpen ? 'rotate-90' : ''}`} />
                        </button>
                        <button
                          type="button"
                          role="treeitem"
                          aria-expanded={objectOpen}
                          onClick={() => toggle(key)}
                          onDoubleClick={() => !object.private && onInsert(qualified(schema.name, object.name))}
                          title={object.private ? 'Holds passwords, sessions, tokens or private messages: not readable here' : `${object.kind}${object.rows !== null ? `, about ${object.rows.toLocaleString('en-IN')} rows` : ''}, ${bytes(object.size)}${object.comment ? `\n${object.comment}` : ''}\nDouble-click to put the name in the editor; right-click for more`}
                          className="flex min-w-0 flex-1 items-center gap-1.5 py-1 pr-2 text-left text-[color:var(--color-text)]"
                        >
                          <Icon className={`h-3.5 w-3.5 shrink-0 ${object.private ? 'text-warning' : object.kind === 'table' ? 'text-[color:var(--color-text-muted)]' : 'text-accent'}`} />
                          <span className={`min-w-0 flex-1 truncate ${object.private ? 'text-[color:var(--color-text-faint)]' : ''}`}>{object.name}</span>
                          {object.rows !== null && !object.private && <span className="text-[11px] tabular-nums text-[color:var(--color-text-faint)]">{object.rows >= 1000 ? `${Math.round(object.rows / 100) / 10}k` : object.rows}</span>}
                        </button>
                      </div>
                      {objectOpen && (
                        <ul className="ml-6 border-l border-[color:var(--color-border)] pl-2">
                          {object.columns.map((column) => (
                            <li key={column.name}>
                              <button
                                type="button"
                                onDoubleClick={() => onInsert(quoteName(column.name))}
                                title={`${column.name} ${column.type}${column.nullable ? '' : ' NOT NULL'}${column.default ? ` DEFAULT ${column.default}` : ''}${column.fk ? `\nreferences ${column.fk}` : ''}\nDouble-click to put the name in the editor`}
                                className="flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left text-xs hover:bg-muted"
                              >
                                {column.pk ? <KeyRound className="h-3 w-3 shrink-0 text-warning" /> : column.fk ? <Link2 className="h-3 w-3 shrink-0 text-accent" /> : <span className="h-3 w-3 shrink-0" />}
                                <span className={`min-w-0 flex-1 truncate ${column.nullable ? 'text-[color:var(--color-text-muted)]' : 'font-medium text-[color:var(--color-text)]'}`}>{column.name}</span>
                                <span className="shrink-0 text-[10px] text-[color:var(--color-text-faint)]">{column.type}</span>
                              </button>
                            </li>
                          ))}
                          {object.columns.length === 0 && !object.private && <li className="px-1 py-0.5 text-xs text-[color:var(--color-text-faint)]">No columns.</li>}
                        </ul>
                      )}
                    </div>
                  )
                })}
            </div>
          )
        })}
        {catalog && schemas.length === 0 && <p className="px-3 py-2 text-xs text-[color:var(--color-text-muted)]">Nothing is called that.</p>}
        {!needle && catalog && catalog.functions.length > 0 && (
          <div role="none" className="mt-1">
            <button type="button" onClick={() => toggle('~functions')} className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left font-medium text-[color:var(--color-text)] hover:bg-muted">
              <ChevronRight className={`h-3.5 w-3.5 shrink-0 transition-transform ${open.has('~functions') ? 'rotate-90' : ''}`} />
              <span className="min-w-0 flex-1 truncate">Functions</span>
              <span className="text-[11px] tabular-nums text-[color:var(--color-text-faint)]">{catalog.functions.length}</span>
            </button>
            {open.has('~functions') &&
              catalog.functions.map((fn) => (
                <button key={`${fn.schema}.${fn.name}.${fn.args}`} type="button" onDoubleClick={() => onInsert(`${qualified(fn.schema, fn.name)}()`)} title={`${fn.schema}.${fn.name}(${fn.args}) returns ${fn.returns}`} className="ml-5 block w-[calc(100%-1.25rem)] truncate rounded px-2 py-0.5 text-left text-xs text-[color:var(--color-text-muted)] hover:bg-muted">
                  {fn.schema}.{fn.name}({fn.args})
                </button>
              ))}
          </div>
        )}
      </div>
      {menu && <ContextMenu x={menu.x} y={menu.y} items={menu.items} onClose={() => setMenu(null)} />}
    </div>
  )
}
