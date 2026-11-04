/**
 * Checks what a browser downloads before it can show anything, from the production build. Run after the build:
 *
 *     cd frontend && npm run build && npm run check:bundle
 *
 * Orion's pages are fetched when they are opened (src/lazyPage.tsx), so opening the app costs only the files named in index.html.
 * That list is easy to bloat without noticing: one `import` of a page, or of the chart library, from something the shell uses
 * pulls the whole thing back in. This fails when the start-up files are over budget or hold what must wait for a page.
 */

import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const here = dirname(fileURLToPath(import.meta.url))
const dist = resolve(here, '../dist')

// Measured when the pages were made lazy: 497 kB (about 149 kB gzipped). The budget leaves room for ordinary growth, not for a
// library or a page that should be fetched on demand.
const BUDGET_RAW = 650_000
const BUDGET_GZIP = 200_000
// Libraries that only some pages use. If one of these is among the start-up files, something eager imports it.
const MUST_WAIT = [/^vendor-charts-/, /^ChartBlock-/, /Dashboard.*\.js$/, /^BillEditorPage-/, /^MessagesPage-/, /^AdminPage-/]

let failures = 0
const fail = (message) => {
  failures += 1
  console.log(`FAIL ${message}`)
}

if (!existsSync(join(dist, 'index.html'))) {
  console.log('FAIL there is no dist/index.html: run `npm run build` first')
  process.exit(1)
}

const html = readFileSync(join(dist, 'index.html'), 'utf8')
const files = [...html.matchAll(/(?:src|href)="\/(assets\/[^"]+\.js)"/g)].map((match) => match[1])
if (!files.length) fail('index.html names no script')

let raw = 0
let gzip = 0
for (const file of files) {
  const bytes = readFileSync(join(dist, file))
  raw += bytes.length
  gzip += gzipSync(bytes).length
  const name = file.replace('assets/', '')
  if (MUST_WAIT.some((pattern) => pattern.test(name))) fail(`${name} is loaded at start-up; it should wait until a page needs it (something eager imports it)`)
}
if (raw > BUDGET_RAW) fail(`start-up scripts are ${(raw / 1000).toFixed(0)} kB; the budget is ${BUDGET_RAW / 1000} kB`)
if (gzip > BUDGET_GZIP) fail(`start-up scripts are ${(gzip / 1000).toFixed(0)} kB gzipped; the budget is ${BUDGET_GZIP / 1000} kB`)

// And the pages really are separate files: a build with no page chunks would pass the checks above for the wrong reason.
const chunks = readdirSync(join(dist, 'assets')).filter((name) => name.endsWith('.js'))
for (const page of ['BillingPage', 'DocumentCenterPage', 'EtlPage', 'OverviewDashboard']) {
  if (!chunks.some((name) => name.startsWith(`${page}-`))) fail(`${page} is not a file of its own`)
}

console.log(
  failures
    ? `\n${failures} problem(s).`
    : `Start-up downloads ${files.length} scripts, ${(raw / 1000).toFixed(0)} kB (${(gzip / 1000).toFixed(0)} kB gzipped); ${chunks.length} files in all.`,
)
process.exit(failures ? 1 : 0)
