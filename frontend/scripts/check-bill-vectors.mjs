/**
 * Checks the bill preview's arithmetic against the golden vectors the server's arithmetic is also tested against.
 * Run:  cd frontend && npm run check:bill
 *
 * backend/app/billing.py decides what a person is billed; frontend/src/billing/billCalc.ts only shows it live while they type. The two
 * are written twice, so both must produce exactly the figures in backend/tests/bill_vectors.json (the server side of the same file is
 * checked by backend/tests/test_bill_vectors.py). A mismatch here means the preview would show one total and the saved bill another.
 *
 * It bundles billCalc.ts with esbuild (already a dependency of Vite) into a temporary folder.
 */

import { build } from 'esbuild'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const vectorsFile = process.argv[2] ? resolve(process.argv[2]) : resolve(here, '../../backend/tests/bill_vectors.json')
const out = mkdtempSync(join(tmpdir(), 'orion-bill-'))

let failures = 0
let checked = 0
const fail = (message) => {
  failures += 1
  console.log(`FAIL ${message}`)
}

/** Two decimals, as text: the server's figures are exact decimals, the preview's are numbers, so compare them as the page prints them. */
const text = (value) => (Math.abs(value) < 0.005 ? 0 : value).toFixed(2)

const FIELDS = ['lines_total', 'epf_amount', 'esic_amount', 'sub_total', 'service_amount', 'taxable_total', 'cgst_amount', 'sgst_amount', 'round_off', 'grand_total']

/** A vector's line layout may name only what differs from quantity x rate. */
const UNIT_SETUP = { basis: 'unit', qty_multiplies: true, month_days: null, totals_row: false, charge_by_line: false, service_on: 'lines', labels: {}, columns: [] }

function observed(calculate, DEFAULT_RATES, vector) {
  // The server calls a line's entered amount amount_manual; the editor's line calls it manual.
  const lines = vector.lines.map((line) => ({ ...line, manual: line.amount_manual }))
  const result = calculate(lines, { ...DEFAULT_RATES, ...vector.rates }, vector.extras, { ...UNIT_SETUP, ...vector.setup }, vector.month ?? '', vector.manual ?? {})
  if (!result.ok) return { ok: false }
  const figures = result.figures
  const seen = { ok: true, lines: figures.lines.map((line) => text(line.amount)) }
  for (const field of FIELDS) seen[field] = text(figures[field])
  seen.extras = figures.extra_charges.map((charge) => text(charge.amount))
  return seen
}

try {
  await build({
    entryPoints: { billCalc: resolve(here, '../src/billing/billCalc.ts') },
    bundle: true,
    format: 'esm',
    platform: 'node',
    outdir: out,
    logLevel: 'error',
  })
  const { calculate, DEFAULT_RATES } = await import(pathToFileURL(join(out, 'billCalc.js')).href)
  const file = JSON.parse(readFileSync(vectorsFile, 'utf8'))

  const compare = (name, expected, seen) => {
    checked += 1
    if (expected.ok !== seen.ok) return fail(`${name}: expected ${expected.ok ? 'a bill' : 'a refusal'}, the preview gave ${seen.ok ? 'a bill' : 'a refusal'}`)
    if (!expected.ok) return
    for (const key of ['lines', ...FIELDS, 'extras']) {
      if (JSON.stringify(expected[key]) !== JSON.stringify(seen[key])) {
        return fail(`${name}: ${key} should be ${JSON.stringify(expected[key])}, the preview gave ${JSON.stringify(seen[key])}`)
      }
    }
  }

  for (const vector of file.vectors) compare(vector.name, vector.expect, observed(calculate, DEFAULT_RATES, vector))
  for (const vector of file.differences) compare(`${vector.name} (documented difference)`, vector.frontend, observed(calculate, DEFAULT_RATES, vector))

  if (!file.vectors.length) fail('the vector file holds no vectors')
} catch (error) {
  fail(`could not run: ${error?.message ?? error}`)
} finally {
  rmSync(out, { recursive: true, force: true })
}

console.log(failures ? `\n${failures} failure(s) in ${checked} checks.` : `Bill arithmetic matches the server on all ${checked} vectors.`)
process.exit(failures ? 1 : 0)
