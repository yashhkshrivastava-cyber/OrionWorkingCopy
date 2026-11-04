/**
 * Checks the pure parts of the Lumen interface: which columns of a table become coloured pills, which colour a status word gets, and how a figure's
 * number is found for the count-up. Run:  cd frontend && npm run check:lumen
 *
 * It bundles src/lumen/cells.tsx with esbuild (already a dependency of Vite) into a temporary folder.
 */

import { build } from 'esbuild'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const out = mkdtempSync(join(tmpdir(), 'orion-lumen-'))
let failures = 0
let checked = 0
const expect = (what, got, want) => {
  checked += 1
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    failures += 1
    console.log(`FAIL ${what}\n  got  ${JSON.stringify(got)}\n  want ${JSON.stringify(want)}`)
  }
}

try {
  await build({
    entryPoints: [resolve(here, '../src/lumen/cells.tsx')],
    bundle: true,
    format: 'esm',
    platform: 'node',
    jsx: 'automatic',
    outfile: join(out, 'cells.mjs'),
    logLevel: 'silent',
  })
  const { hueFor, pillColumns, figureColumns } = await import(pathToFileURL(join(out, 'cells.mjs')).href)

  // a status word keeps its meaning, and any other word keeps one colour everywhere
  expect('good words are green', ['Active', 'PAID', 'Closed Won'].map(hueFor), ['green', 'green', 'green'])
  expect('bad words are coral', ['Inactive', 'overdue', 'Cancelled', 'Closed Lost'].map(hueFor), ['coral', 'coral', 'coral', 'coral'])
  expect('waiting words are amber', ['Pending', 'Draft', 'In Progress'].map(hueFor), ['amber', 'amber', 'amber'])
  expect('the same word is always the same colour', hueFor('Hospitality'), hueFor('Hospitality'))

  const rows = Array.from({ length: 12 }, (_, i) => ({
    code: `CS-${String(i + 1).padStart(4, '0')}`,
    name: `Site number ${i} with a long enough name to read as a name`,
    status: i % 2 ? 'Active' : 'Inactive',
    city: ['Gwalior', 'Bhopal', 'Indore'][i % 3],
    amount: String(1000 + i),
    when: `2026-0${(i % 9) + 1}-01`,
  }))
  const kinds = { code: 'text', name: 'text', status: 'text', city: 'text', amount: 'number', when: 'text' }
  const pills = [...pillColumns(Object.keys(kinds), rows, kinds)].sort()
  expect('a status column and a short list of words become pills; codes, names, numbers and dates do not', pills, ['city', 'status'])

  // text written as figures is never a status, and lines up on the right
  const money = Array.from({ length: 12 }, (_, i) => ({ month: `M${i}`, tax: i % 3 ? '5,39,377.90' : '—', net: i % 2 ? '−1,200.00' : '29,017.63' }))
  const moneyKinds = { month: 'text', tax: 'text', net: 'text' }
  expect('a column of figures is not made into pills', [...pillColumns(['tax', 'net'], money, moneyKinds)], [])
  expect('a column of figures written with commas lines up on the right', [...figureColumns(['month', 'tax', 'net'], money)].sort(), ['net', 'tax'])

  const few = rows.slice(0, 3)
  expect('a short table does not guess', [...pillColumns(['city'], few, kinds)], [])
} finally {
  rmSync(out, { recursive: true, force: true })
}

console.log(failures ? `Lumen: ${failures} of ${checked} checks FAILED` : `Lumen: all ${checked} checks pass.`)
process.exit(failures ? 1 : 0)
