/**
 * What the letter editor does to the text. The editor is a contentEditable element; these are the commands
 * its toolbar runs and the tidying it does to pasted text.
 *
 * The server rebuilds a letter from a short list of tags before saving it (letterhead.clean_html). The list
 * here is the same, so that what is pasted already looks the way it will after saving.
 */

const RENAME: Record<string, string> = { strong: 'b', em: 'i', div: 'p', h1: 'h2', h4: 'h3', h5: 'h3', h6: 'h3', strike: 's', del: 's' }
const KEEP = new Set(['p', 'h2', 'h3', 'ul', 'ol', 'li', 'table', 'thead', 'tbody', 'tr', 'td', 'th', 'b', 'i', 'u', 's', 'sub', 'sup', 'br', 'hr'])
const DROP_WITH_CONTENT = new Set(['script', 'style', 'head', 'title', 'iframe', 'object', 'embed', 'svg', 'math', 'noscript', 'template', 'meta', 'link'])
const ALIGNABLE = new Set(['p', 'h2', 'h3', 'li', 'td', 'th'])
const ALIGNMENTS = new Set(['center', 'right', 'justify'])

const escapeText = (text: string) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

function cleanNode(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return escapeText(node.textContent ?? '')
  if (node.nodeType !== Node.ELEMENT_NODE) return ''
  const element = node as HTMLElement
  const original = element.tagName.toLowerCase()
  if (DROP_WITH_CONTENT.has(original)) return ''
  const tag = RENAME[original] ?? original
  const inner = Array.from(element.childNodes).map(cleanNode).join('')
  if (!KEEP.has(tag)) return inner
  if (tag === 'br' || tag === 'hr') return `<${tag}>`
  let attributes = ''
  if (ALIGNABLE.has(tag)) {
    const align = (element.style.textAlign || element.getAttribute('align') || '').toLowerCase()
    if (ALIGNMENTS.has(align)) attributes += ` style="text-align:${align}"`
  }
  if (tag === 'td' || tag === 'th') {
    for (const name of ['colspan', 'rowspan']) {
      const span = Number(element.getAttribute(name))
      if (Number.isInteger(span) && span > 1 && span <= 20) attributes += ` ${name}="${span}"`
    }
  }
  if (tag === 'p' && element.getAttribute('data-break') === 'page') attributes += ' data-break="page"'
  return `<${tag}${attributes}>${inner}</${tag}>`
}

/** Text copied from Word, Excel or a web page, kept as paragraphs, bold, lists and tables and nothing else. */
export function cleanPastedHtml(html: string): string {
  const parsed = new DOMParser().parseFromString(html, 'text/html')
  return Array.from(parsed.body.childNodes).map(cleanNode).join('')
}

/** Plain text as paragraphs, one per line. */
export function textToHtml(text: string): string {
  return text
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map((line) => `<p>${escapeText(line) || '<br>'}</p>`)
    .join('')
}

/** Runs one of the browser's editing commands on the selection. */
export function run(command: string, value?: string) {
  document.execCommand(command, false, value)
}

/** Makes the browser write plain tags (<b>, <p>) rather than styled spans, which the server would strip. */
export function prepareEditor() {
  try {
    document.execCommand('styleWithCSS', false, 'false')
    document.execCommand('defaultParagraphSeparator', false, 'p')
  } catch {
    /* an old browser: the server tidies the result anyway */
  }
}

export function tableHtml(rows: number, columns: number, headings = true): string {
  const row = (cell: 'th' | 'td') => `<tr>${Array.from({ length: columns }, () => `<${cell}><br></${cell}>`).join('')}</tr>`
  const body = Array.from({ length: rows }, (_, index) => row(headings && index === 0 ? 'th' : 'td')).join('')
  // The empty paragraph after it gives somewhere to click below the table.
  return `<table><tbody>${body}</tbody></table><p><br></p>`
}

/** The table cell the cursor is in, when it is inside `root`. */
export function currentCell(root: HTMLElement | null): HTMLTableCellElement | null {
  const selection = window.getSelection()
  if (!root || !selection || selection.rangeCount === 0) return null
  let node: Node | null = selection.anchorNode
  while (node && node !== root) {
    if (node instanceof HTMLTableCellElement) return root.contains(node) ? node : null
    node = node.parentNode
  }
  return null
}

function placeCursor(cell: Element | null | undefined) {
  if (!cell) return
  const range = document.createRange()
  range.selectNodeContents(cell)
  range.collapse(true)
  const selection = window.getSelection()
  selection?.removeAllRanges()
  selection?.addRange(range)
}

export type TableChange = 'row-below' | 'column-right' | 'delete-row' | 'delete-column' | 'delete-table'

/** Adds or removes a row or column next to the cell the cursor is in. Returns false when it is not in a table. */
export function changeTable(root: HTMLElement | null, change: TableChange): boolean {
  const cell = currentCell(root)
  const row = cell?.parentElement as HTMLTableRowElement | null
  const table = cell?.closest('table')
  if (!cell || !row || !table) return false
  const index = cell.cellIndex
  const rows = Array.from(table.rows)

  if (change === 'delete-table') {
    table.remove()
    return true
  }
  if (change === 'row-below') {
    const added = document.createElement('tr')
    for (let i = 0; i < row.cells.length; i += 1) {
      const next = document.createElement('td')
      next.innerHTML = '<br>'
      // A column of amounts stays right-aligned in the new row.
      if (row.cells[i].style.textAlign) next.style.textAlign = row.cells[i].style.textAlign
      added.appendChild(next)
    }
    row.after(added)
    placeCursor(added.cells[Math.min(index, added.cells.length - 1)])
    return true
  }
  if (change === 'column-right') {
    for (const each of rows) {
      const beside = each.cells[Math.min(index, each.cells.length - 1)]
      const next = document.createElement(beside?.tagName.toLowerCase() === 'th' ? 'th' : 'td')
      next.innerHTML = '<br>'
      if (beside) beside.after(next)
      else each.appendChild(next)
    }
    placeCursor(row.cells[index + 1])
    return true
  }
  if (change === 'delete-row') {
    if (rows.length <= 1) table.remove()
    else {
      const neighbour = rows[row.rowIndex + 1] ?? rows[row.rowIndex - 1]
      row.remove()
      placeCursor(neighbour?.cells[Math.min(index, neighbour.cells.length - 1)])
    }
    return true
  }
  // delete-column
  if (row.cells.length <= 1) table.remove()
  else {
    for (const each of rows) each.cells[Math.min(index, each.cells.length - 1)]?.remove()
    placeCursor(row.cells[Math.max(index - 1, 0)])
  }
  return true
}

/** True when the editor holds nothing a reader would see. */
export function isBlank(html: string): boolean {
  return html.replace(/<(br|p|\/p)\s*\/?>/gi, '').replace(/&nbsp;/g, ' ').trim() === ''
}
