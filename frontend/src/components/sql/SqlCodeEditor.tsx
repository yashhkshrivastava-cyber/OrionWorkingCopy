import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { autocompletion, closeBrackets, completionKeymap } from '@codemirror/autocomplete'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { bracketMatching, defaultHighlightStyle, HighlightStyle, indentOnInput, syntaxHighlighting } from '@codemirror/language'
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search'
import { Compartment, EditorSelection, EditorState, type Extension } from '@codemirror/state'
import { drawSelection, EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers, placeholder } from '@codemirror/view'
import { PostgreSQL, sql, type SQLNamespace } from '@codemirror/lang-sql'
import { tags } from '@lezer/highlight'

/** What the page can ask of the editor: the text, the selection, the statement under the cursor, and to put text in or move the cursor. */
export interface SqlCodeEditorHandle {
  getText: () => string
  /** The selected text, or '' when nothing is selected. */
  getSelection: () => string
  /** The statement the cursor is in (between the semicolons around it). */
  getStatementAtCursor: () => string
  setText: (text: string) => void
  insert: (text: string) => void
  focus: () => void
  /** Put the cursor on a line and column (1-based) and select the line, for an error's position. */
  goTo: (line: number, column?: number) => void
}

// The colours come from the app's own tokens, so the editor follows the chosen theme.
const highlight = HighlightStyle.define([
  { tag: [tags.keyword, tags.operatorKeyword, tags.modifier], color: 'var(--orion-accent)', fontWeight: '600' },
  { tag: [tags.string, tags.special(tags.string)], color: 'var(--color-positive, #2e9e6b)' },
  { tag: [tags.number, tags.bool, tags.null], color: 'var(--color-warning, #c98a0b)' },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: 'var(--color-text-faint)', fontStyle: 'italic' },
  { tag: [tags.typeName, tags.standard(tags.name)], color: 'var(--color-text)' },
  { tag: [tags.function(tags.variableName)], color: 'var(--orion-accent)' },
  { tag: [tags.punctuation, tags.operator], color: 'var(--color-text-muted)' },
])

const theme = EditorView.theme({
  '&': { height: '100%', backgroundColor: 'var(--orion-surface)', color: 'var(--color-text)', fontSize: '13px' },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace', lineHeight: '1.55' },
  '.cm-content': { caretColor: 'var(--color-text)', padding: '8px 0' },
  '.cm-gutters': { backgroundColor: 'var(--orion-surface)', color: 'var(--color-text-faint)', border: 'none' },
  '.cm-activeLine': { backgroundColor: 'color-mix(in srgb, var(--orion-accent) 7%, transparent)' },
  '.cm-activeLineGutter': { backgroundColor: 'transparent', color: 'var(--color-text)' },
  '.cm-selectionBackground, &.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground': { backgroundColor: 'color-mix(in srgb, var(--orion-accent) 28%, transparent)' },
  '.cm-cursor': { borderLeftColor: 'var(--color-text)' },
  '.cm-tooltip': { backgroundColor: 'var(--orion-surface)', border: '1px solid var(--color-border)', borderRadius: '8px', color: 'var(--color-text)' },
  '.cm-tooltip-autocomplete ul li[aria-selected]': { backgroundColor: 'color-mix(in srgb, var(--orion-accent) 22%, transparent)', color: 'var(--color-text)' },
  '.cm-completionDetail': { color: 'var(--color-text-faint)' },
  '.cm-matchingBracket': { backgroundColor: 'color-mix(in srgb, var(--orion-accent) 25%, transparent)' },
  '.cm-placeholder': { color: 'var(--color-text-faint)' },
})

function statementAround(text: string, at: number): string {
  // Between the semicolons nearest the cursor; a semicolon inside quotes is not found, which is right often enough for "run this one".
  const before = text.lastIndexOf(';', Math.max(0, at - 1))
  const after = text.indexOf(';', at)
  return text.slice(before + 1, after < 0 ? text.length : after).trim()
}

/**
 * A SQL editor (CodeMirror 6): line numbers, PostgreSQL highlighting, bracket matching, undo, find and replace (Ctrl+F), and autocomplete from the
 * database's own tables and columns. It keeps its own text; the page reads it when it runs, saves or formats.
 */
export const SqlCodeEditor = forwardRef<
  SqlCodeEditorHandle,
  {
    initial: string
    schema: SQLNamespace
    onChange?: (text: string) => void
    onRun: (mode: 'all' | 'statement') => void
    onSave: () => void
    onFormat: () => void
    /** Changes when the tab shown changes: the editor is given that tab's text. */
    tabKey: string
  }
>(function SqlCodeEditor({ initial, schema, onChange, onRun, onSave, onFormat, tabKey }, ref) {
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const language = useRef(new Compartment())
  const callbacks = useRef({ onChange, onRun, onSave, onFormat })
  callbacks.current = { onChange, onRun, onSave, onFormat }

  useEffect(() => {
    if (!host.current) return
    const extensions: Extension[] = [
      lineNumbers(),
      highlightActiveLineGutter(),
      history(),
      drawSelection(),
      indentOnInput(),
      bracketMatching(),
      closeBrackets(),
      highlightActiveLine(),
      highlightSelectionMatches(),
      syntaxHighlighting(highlight),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      autocompletion({ activateOnTyping: true }),
      language.current.of(sql({ dialect: PostgreSQL, schema, defaultSchema: 'orion_ods', upperCaseKeywords: true })),
      placeholder('Write SQL here. Ctrl+Enter runs it; Ctrl+Shift+Enter runs the statement the cursor is in.'),
      EditorView.lineWrapping,
      keymap.of([
        { key: 'Mod-Enter', run: () => (callbacks.current.onRun('all'), true) },
        { key: 'Mod-Shift-Enter', run: () => (callbacks.current.onRun('statement'), true) },
        { key: 'Mod-s', run: () => (callbacks.current.onSave(), true) },
        { key: 'Mod-Shift-f', run: () => (callbacks.current.onFormat(), true) },
        indentWithTab,
        ...completionKeymap,
        ...searchKeymap,
        ...historyKeymap,
        ...defaultKeymap,
      ]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) callbacks.current.onChange?.(update.state.doc.toString())
      }),
      theme,
    ]
    view.current = new EditorView({ state: EditorState.create({ doc: initial, extensions }), parent: host.current })
    return () => {
      view.current?.destroy()
      view.current = null
    }
    // The editor is made once; the tab's text and the schema are given to it below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Another tab: its text replaces this one's, and the cursor starts at the end.
  useEffect(() => {
    const v = view.current
    if (!v || v.state.doc.toString() === initial) return
    v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: initial }, selection: EditorSelection.cursor(initial.length) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabKey])

  // The database's tables and columns arrive after the editor is made.
  useEffect(() => {
    view.current?.dispatch({ effects: language.current.reconfigure(sql({ dialect: PostgreSQL, schema, defaultSchema: 'orion_ods', upperCaseKeywords: true })) })
  }, [schema])

  useImperativeHandle(ref, () => ({
    getText: () => view.current?.state.doc.toString() ?? '',
    getSelection: () => {
      const v = view.current
      if (!v) return ''
      const range = v.state.selection.main
      return range.empty ? '' : v.state.sliceDoc(range.from, range.to)
    },
    getStatementAtCursor: () => {
      const v = view.current
      return v ? statementAround(v.state.doc.toString(), v.state.selection.main.head) : ''
    },
    setText: (text: string) => {
      const v = view.current
      v?.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: text } })
    },
    insert: (text: string) => {
      const v = view.current
      if (!v) return
      const range = v.state.selection.main
      v.dispatch({ changes: { from: range.from, to: range.to, insert: text }, selection: EditorSelection.cursor(range.from + text.length) })
      v.focus()
    },
    focus: () => view.current?.focus(),
    goTo: (line: number, column = 1) => {
      const v = view.current
      if (!v) return
      const info = v.state.doc.line(Math.max(1, Math.min(line, v.state.doc.lines)))
      const at = Math.min(info.to, info.from + Math.max(0, column - 1))
      v.dispatch({ selection: EditorSelection.range(at, info.to), scrollIntoView: true })
      v.focus()
    },
  }))

  return <div ref={host} className="h-full min-h-0 overflow-hidden" />
})
