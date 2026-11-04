import { Fragment, type ReactNode } from 'react'
import { TabLink } from '../ui/TabLink'
import { splitBillNumbers } from '../../billing/billLink'
import { BillNumber } from '../billing/BillNumber'

/*
 * A small, safe Markdown renderer for the Copilot's answers: paragraphs, headings, bold and italic, code, lists, quotes,
 * tables and links. It builds React elements and never injects HTML, so nothing an answer contains can run as script,
 * and only same-site paths and http(s) addresses become links.
 */

const INLINE = /(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*\s][^*]*\*|https?:\/\/[^\s<)]+)/g

function Anchor({ href, children }: { href: string; children: ReactNode }) {
  const cls = 'font-medium text-accent underline decoration-[color:var(--color-border-strong)] underline-offset-2 hover:decoration-current'
  if (href.startsWith('/') && !href.startsWith('//')) {
    return (
      <TabLink to={href} className={cls}>
        {children}
      </TabLink>
    )
  }
  if (/^https?:\/\//i.test(href)) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={cls}>
        {children}
      </a>
    )
  }
  return <>{children}</>
}

/** Plain text, with each bill number in it made a link to the bill (a card on hover, the bill in a new tab). */
function plain(text: string, key: string): ReactNode[] {
  return splitBillNumbers(text).map((piece, at) => (piece.bill ? <BillNumber key={`${key}-${at}`} number={piece.text} /> : piece.text))
}

function inline(text: string, keyBase = 'i'): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let n = 0
  for (const match of text.matchAll(INLINE)) {
    const at = match.index ?? 0
    if (at > last) out.push(...plain(text.slice(last, at), `${keyBase}-p${n}`))
    const token = match[0]
    const key = `${keyBase}-${n++}`
    if (token.startsWith('**') || token.startsWith('__')) {
      out.push(
        <strong key={key} className="font-semibold text-[color:var(--color-text)]">
          {inline(token.slice(2, -2), key)}
        </strong>,
      )
    } else if (token.startsWith('`')) {
      out.push(
        <code key={key} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">
          {token.slice(1, -1)}
        </code>,
      )
    } else if (token.startsWith('[')) {
      const split = token.indexOf('](')
      out.push(
        <Anchor key={key} href={token.slice(split + 2, -1)}>
          {token.slice(1, split)}
        </Anchor>,
      )
    } else if (token.startsWith('*')) {
      out.push(<em key={key}>{inline(token.slice(1, -1), key)}</em>)
    } else {
      const clean = token.replace(/[.,;:!?]+$/, '')
      out.push(
        <Anchor key={key} href={clean}>
          {clean}
        </Anchor>,
      )
      if (clean.length < token.length) out.push(token.slice(clean.length))
    }
    last = at + token.length
  }
  if (last < text.length) out.push(...plain(text.slice(last), `${keyBase}-end`))
  return out
}

const isTableRow = (line: string) => /^\s*\|.*\|\s*$/.test(line)
const isTableRule = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line) && line.includes('-')
const cells = (line: string) =>
  line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let k = 0
  while (i < lines.length) {
    const line = lines[i]
    const key = `b${k++}`
    if (!line.trim()) {
      i += 1
      continue
    }
    if (/^\s*```/.test(line)) {
      const body: string[] = []
      i += 1
      while (i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i++])
      i += 1
      blocks.push(
        <pre key={key} className="overflow-x-auto rounded-lg bg-muted px-3 py-2.5 font-mono text-[12px] leading-relaxed">
          {body.join('\n')}
        </pre>,
      )
      continue
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      blocks.push(
        <p key={key} className="t-h3 pt-1 text-[color:var(--color-text)]">
          {inline(heading[2], key)}
        </p>,
      )
      i += 1
      continue
    }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      blocks.push(<hr key={key} className="border-[color:var(--color-border)]" />)
      i += 1
      continue
    }
    if (isTableRow(line) && i + 1 < lines.length && isTableRule(lines[i + 1])) {
      const head = cells(line)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && isTableRow(lines[i])) rows.push(cells(lines[i++]))
      blocks.push(
        <div key={key} className="overflow-x-auto rounded-lg border border-[color:var(--color-border)]">
          <table className="w-full border-collapse text-left text-[13px]">
            <thead className="bg-muted/70">
              <tr>
                {head.map((cell, c) => (
                  <th key={c} className="px-3 py-1.5 text-xs font-semibold text-[color:var(--color-text-muted)]">
                    {inline(cell, `${key}h${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, r) => (
                <tr key={r} className="border-t border-[color:var(--color-border)]">
                  {row.map((cell, c) => (
                    <td key={c} className="t-num px-3 py-1.5 align-top">
                      {inline(cell, `${key}r${r}c${c}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }
    const listItem = /^(\s*)([-*•]|\d+[.)])\s+(.*)$/.exec(line)
    if (listItem) {
      const ordered = /\d/.test(listItem[2])
      const items: string[] = []
      while (i < lines.length) {
        const m = /^(\s*)([-*•]|\d+[.)])\s+(.*)$/.exec(lines[i])
        if (!m || /\d/.test(m[2]) !== ordered) break
        let item = m[3]
        i += 1
        // A wrapped continuation line belongs to the item above it.
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) item += ' ' + lines[i++].trim()
        items.push(item)
      }
      const List = ordered ? 'ol' : 'ul'
      blocks.push(
        <List key={key} className={`space-y-1 pl-5 ${ordered ? 'list-decimal' : 'list-disc'} marker:text-[color:var(--color-text-faint)]`}>
          {items.map((item, n) => (
            <li key={n} className="pl-0.5">
              {inline(item, `${key}l${n}`)}
            </li>
          ))}
        </List>,
      )
      continue
    }
    if (/^\s*>/.test(line)) {
      const quote: string[] = []
      while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ''))
      blocks.push(
        <blockquote key={key} className="border-l-2 border-[color:var(--color-border-strong)] pl-3 text-[color:var(--color-text-muted)]">
          {inline(quote.join(' '), key)}
        </blockquote>,
      )
      continue
    }
    const paragraph: string[] = []
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^\s*```/.test(lines[i]) &&
      !/^(#{1,4})\s+/.test(lines[i]) &&
      !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i]) &&
      !/^\s*>/.test(lines[i]) &&
      !(isTableRow(lines[i]) && i + 1 < lines.length && isTableRule(lines[i + 1]))
    ) {
      paragraph.push(lines[i++])
    }
    blocks.push(
      <p key={key}>
        {paragraph.map((row, n) => (
          <Fragment key={n}>
            {n > 0 && <br />}
            {inline(row, `${key}p${n}`)}
          </Fragment>
        ))}
      </p>,
    )
  }
  return <div className="t-body space-y-2.5 break-words text-[color:var(--color-text)]">{blocks}</div>
}
