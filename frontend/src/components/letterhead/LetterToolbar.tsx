import { useState, type ReactNode, type RefObject } from 'react'
import {
  Bold,
  Columns3,
  Italic,
  List,
  ListOrdered,
  Minus,
  Redo2,
  Rows3,
  SquareSplitVertical,
  Table,
  TextAlignCenter,
  TextAlignEnd,
  TextAlignJustify,
  TextAlignStart,
  Trash2,
  Underline,
  Undo2,
  type LucideIcon,
} from 'lucide-react'
import { changeTable, currentCell, run, tableHtml, type TableChange } from './richText'

function Tool({
  label,
  icon: Icon,
  onRun,
  disabled,
  children,
}: {
  label: string
  icon?: LucideIcon
  onRun: () => void
  disabled?: boolean
  children?: ReactNode
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      // Pressing a tool must not take the cursor out of the letter, or the command has nothing to act on.
      onMouseDown={(event) => event.preventDefault()}
      onClick={onRun}
      className="interactive inline-flex h-8 min-w-8 items-center justify-center gap-1 rounded-md px-1.5 text-xs font-medium text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)] focus-visible:ring-2 focus-visible:ring-accent disabled:pointer-events-none disabled:opacity-40"
    >
      {Icon && <Icon className="h-4 w-4" aria-hidden="true" />}
      {children}
    </button>
  )
}

const Divider = () => <span className="mx-1 h-5 w-px shrink-0 bg-[color:var(--color-border)]" aria-hidden="true" />

/**
 * The formatting bar above a letter. Every tool acts on the selection inside `editor`, and calls `onChange`
 * so the page knows the letter has been edited.
 */
export function LetterToolbar({ editor, onChange }: { editor: RefObject<HTMLDivElement | null>; onChange: () => void }) {
  const [pickingTable, setPickingTable] = useState(false)
  const [rows, setRows] = useState(4)
  const [columns, setColumns] = useState(3)
  /** Whether the cursor is in a table, checked when the bar is touched so the table tools enable in time. */
  const [inTable, setInTable] = useState(false)

  const act = (command: string, value?: string) => {
    editor.current?.focus()
    run(command, value)
    onChange()
  }

  const table = (change: TableChange) => {
    if (changeTable(editor.current, change)) onChange()
    setInTable(Boolean(currentCell(editor.current)))
  }

  const insertTable = () => {
    setPickingTable(false)
    act('insertHTML', tableHtml(Math.min(Math.max(rows, 1), 40), Math.min(Math.max(columns, 1), 10)))
  }

  return (
    <div
      role="toolbar"
      aria-label="Formatting"
      onMouseEnter={() => setInTable(Boolean(currentCell(editor.current)))}
      className="relative flex flex-wrap items-center gap-0.5 rounded-xl border border-[color:var(--color-border)] bg-surface px-2 py-1.5 shadow-card"
    >
      <Tool label="Undo" icon={Undo2} onRun={() => act('undo')} />
      <Tool label="Redo" icon={Redo2} onRun={() => act('redo')} />
      <Divider />
      <Tool label="Normal text" onRun={() => act('formatBlock', 'P')}>
        Text
      </Tool>
      <Tool label="Heading" onRun={() => act('formatBlock', 'H2')}>
        Heading
      </Tool>
      <Tool label="Small heading" onRun={() => act('formatBlock', 'H3')}>
        Sub-heading
      </Tool>
      <Divider />
      <Tool label="Bold" icon={Bold} onRun={() => act('bold')} />
      <Tool label="Italic" icon={Italic} onRun={() => act('italic')} />
      <Tool label="Underline" icon={Underline} onRun={() => act('underline')} />
      <Divider />
      <Tool label="Align left" icon={TextAlignStart} onRun={() => act('justifyLeft')} />
      <Tool label="Centre" icon={TextAlignCenter} onRun={() => act('justifyCenter')} />
      <Tool label="Align right" icon={TextAlignEnd} onRun={() => act('justifyRight')} />
      <Tool label="Justify" icon={TextAlignJustify} onRun={() => act('justifyFull')} />
      <Divider />
      <Tool label="Bulleted list" icon={List} onRun={() => act('insertUnorderedList')} />
      <Tool label="Numbered list" icon={ListOrdered} onRun={() => act('insertOrderedList')} />
      <Divider />
      <Tool label="Insert a table" icon={Table} onRun={() => setPickingTable((open) => !open)}>
        Table
      </Tool>
      <Tool label="Add a row below" icon={Rows3} disabled={!inTable} onRun={() => table('row-below')}>
        +
      </Tool>
      <Tool label="Add a column to the right" icon={Columns3} disabled={!inTable} onRun={() => table('column-right')}>
        +
      </Tool>
      <Tool label="Delete this row" icon={Rows3} disabled={!inTable} onRun={() => table('delete-row')}>
        −
      </Tool>
      <Tool label="Delete this column" icon={Columns3} disabled={!inTable} onRun={() => table('delete-column')}>
        −
      </Tool>
      <Tool label="Delete the table" icon={Trash2} disabled={!inTable} onRun={() => table('delete-table')} />
      <Divider />
      <Tool label="Line across the page" icon={Minus} onRun={() => act('insertHorizontalRule')} />
      <Tool
        label="Start a new page here"
        icon={SquareSplitVertical}
        onRun={() => act('insertHTML', '<p data-break="page"><br></p><p><br></p>')}
      />

      {pickingTable && (
        <div className="absolute left-2 top-full z-20 mt-1 flex items-end gap-2 rounded-xl border border-[color:var(--color-border)] bg-surface p-3 shadow-overlay">
          <label className="text-xs text-[color:var(--color-text-muted)]">
            Rows
            <input
              type="number"
              min={1}
              max={40}
              value={rows}
              onChange={(event) => setRows(Number(event.target.value))}
              className="mt-1 block h-8 w-16 rounded-md border border-[color:var(--color-border-strong)] bg-surface px-2 text-sm text-[color:var(--color-text)]"
            />
          </label>
          <label className="text-xs text-[color:var(--color-text-muted)]">
            Columns
            <input
              type="number"
              min={1}
              max={10}
              value={columns}
              onChange={(event) => setColumns(Number(event.target.value))}
              className="mt-1 block h-8 w-16 rounded-md border border-[color:var(--color-border-strong)] bg-surface px-2 text-sm text-[color:var(--color-text)]"
            />
          </label>
          <button
            type="button"
            onMouseDown={(event) => event.preventDefault()}
            onClick={insertTable}
            className="interactive h-8 rounded-lg bg-brand-700 px-3 text-xs font-semibold text-white hover:bg-brand-800 dark:bg-brand-500 dark:text-slate-950"
          >
            Insert
          </button>
        </div>
      )}
    </div>
  )
}
