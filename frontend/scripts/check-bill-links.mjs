/**
 * Checks the pieces behind "a bill number is a link with a card, and other screens open in a new tab", without a browser.
 * Run:  cd frontend && npm run check:links
 *
 *  1. Which text is a bill number (and which only looks like one: a financial year, a date, a code with a suffix).
 *  2. Which table columns hold bills, and which values are "no value".
 *  3. Which addresses may be opened in a new tab (only paths inside the app), and how: the native window's bridge when there is
 *     one, an ordinary new tab otherwise.
 *
 * It bundles the modules with esbuild (already a dependency of Vite) into a temporary folder.
 */

import { build } from 'esbuild'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = resolve(here, '../src')
const out = mkdtempSync(join(tmpdir(), 'orion-links-'))

let failures = 0
let checked = 0
const check = (name, ok, detail = '') => {
  checked += 1
  if (!ok) {
    failures += 1
    console.log(`FAIL ${name}${detail ? `: ${detail}` : ''}`)
  }
}
const same = (name, actual, expected) => check(name, JSON.stringify(actual) === JSON.stringify(expected), `got ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`)

try {
  await build({
    entryPoints: { billLink: join(src, 'billing/billLink.ts'), openInNewTab: join(src, 'navigation/openInNewTab.ts') },
    bundle: true,
    format: 'esm',
    platform: 'node',
    outdir: out,
    logLevel: 'error',
  })
  const load = (name) => import(pathToFileURL(join(out, `${name}.js`)).href)
  const { splitBillNumbers, billColumn, isBlankBill, billPath, billByNumberPath } = await load('billLink')

  // 1. bill numbers in text
  const bills = (text) => splitBillNumbers(text).filter((piece) => piece.bill).map((piece) => piece.text)
  same('one number in a sentence', splitBillNumbers('Bill 2026-27/202 was paid.'), [
    { text: 'Bill ', bill: false },
    { text: '2026-27/202', bill: true },
    { text: ' was paid.', bill: false },
  ])
  same('two numbers', bills('2025-26/113 and 2026-27/9'), ['2025-26/113', '2026-27/9'])
  same('in brackets and with punctuation', bills('(see 2026-27/45), 2026-27/46; 2026-27/47?'), ['2026-27/45', '2026-27/46', '2026-27/47'])
  same('a number alone', splitBillNumbers('2026-27/1'), [{ text: '2026-27/1', bill: true }])
  same('no number, one plain piece', splitBillNumbers('Nothing here'), [{ text: 'Nothing here', bill: false }])
  same('empty text', splitBillNumbers(''), [])
  same('a financial year is not a bill', bills('FY 2026-27 results'), [])
  same('a path or a date with the same shape is not a bill', bills('2026-27/10/05'), [])
  same('a code with a suffix is not a bill', bills('2026-27/202-A and 2026-27/202B'), [])
  same('a longer number is not cut short', bills('12026-27/1 and 2026-27/12345678'), [])
  same('the pieces always add back to the text', splitBillNumbers('a 2026-27/1 b 2025-26/22 c').map((p) => p.text).join(''), 'a 2026-27/1 b 2025-26/22 c')

  // 2. columns and blanks
  same('bill_number column', billColumn('bill_number'), 'number')
  same('bill_no column', billColumn('bill_no'), 'number')
  same('bill_code column', billColumn('bill_code'), 'code')
  same('another column', billColumn('billing_month'), null)
  same('a column that only contains the word', billColumn('unbilled_bill_number_x'), null)
  for (const blank of ['', ' ', '—', '–', '-', ' — ', null, undefined]) check(`blank ${JSON.stringify(blank)}`, isBlankBill(blank))
  for (const real of ['2026-27/1', 'BILL-0012']) check(`not blank ${real}`, !isBlankBill(real))

  // addresses
  same('a bill by code', billPath('BILL-0012'), '/utility/billing/BILL-0012')
  same('a bill by number is encoded', billByNumberPath('2026-27/202'), '/utility/billing/find?number=2026-27%2F202')

  // 3. new tab
  const windows = []
  globalThis.window = { open: (...args) => windows.push(args) }
  const { isAppPath, openInNewTab, inNativeWindow } = await load('openInNewTab')
  for (const ok of ['/utility/billing/BILL-0012', '/dashboard/orion?fy=2026', '/']) check(`app path ${ok}`, isAppPath(ok))
  for (const bad of ['https://evil.example', '//evil.example', 'javascript:alert(1)', 'utility', '', '/a\\b', '/a\nb', '/a\rb']) check(`not an app path ${JSON.stringify(bad)}`, !isAppPath(bad))

  check('no native window by default', inNativeWindow() === false)
  openInNewTab('/utility/billing/BILL-0012')
  same('a browser gets a new tab that cannot reach back', windows, [['/utility/billing/BILL-0012', '_blank', 'noopener']])
  windows.length = 0
  openInNewTab('https://evil.example')
  openInNewTab('//evil.example')
  same('an address outside the app opens nothing', windows, [])

  const bridge = []
  globalThis.window = { open: (...args) => windows.push(args), pywebview: { api: { open_window: (path) => Promise.resolve(bridge.push(path)) } } }
  check('the native window is noticed', inNativeWindow() === true)
  openInNewTab('/utility/billing/BILL-0012')
  same('the native window opens its own second window', { bridge, tabs: windows }, { bridge: ['/utility/billing/BILL-0012'], tabs: [] })
  openInNewTab('https://evil.example')
  same('and refuses an address outside the app too', bridge.length, 1)
} catch (error) {
  failures += 1
  console.log(`FAIL could not run: ${error?.message ?? error}`)
} finally {
  rmSync(out, { recursive: true, force: true })
}

console.log(failures ? `\n${failures} failure(s) in ${checked} checks.` : `Bill links and new-tab behaviour: all ${checked} checks pass.`)
process.exit(failures ? 1 : 0)
