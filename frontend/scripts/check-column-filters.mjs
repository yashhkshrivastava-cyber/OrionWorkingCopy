/**
 * Checks the column filters that run in the browser: which rows a condition lets through, the pick list made from rows, what a filter is
 * called on its chip, and what is sent to the server.
 * Run:  cd frontend && npm run check:filters
 *
 * It bundles src/tables/columnFilter.ts with esbuild (already a dependency of Vite) into a temporary folder.
 */

import { build } from 'esbuild'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const out = mkdtempSync(join(tmpdir(), 'orion-filters-'))
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
  await build({ entryPoints: [resolve(here, '../src/tables/columnFilter.ts')], bundle: true, format: 'esm', platform: 'node', outfile: join(out, 'columnFilter.mjs'), logLevel: 'silent' })
  const f = await import(pathToFileURL(join(out, 'columnFilter.mjs')).href)
  const pass = (filter, raw, shown, kind) => f.matchesFilter({ column: 'c', ...filter }, raw, shown ?? String(raw ?? ''), kind)

  // text conditions look at what is shown, without regard to case
  expect('contains', pass({ op: 'contains', value: 'bsn' }, 'BSNL Gwalior', undefined, 'text'), true)
  expect('contains misses', pass({ op: 'contains', value: 'xyz' }, 'BSNL', undefined, 'text'), false)
  expect('not_contains', pass({ op: 'not_contains', value: 'bsn' }, 'BSNL', undefined, 'text'), false)
  expect('equals is whole and any case', [pass({ op: 'equals', value: 'won' }, 'Won', undefined, 'text'), pass({ op: 'equals', value: 'wo' }, 'Won', undefined, 'text')], [true, false])
  expect('starts / ends', [pass({ op: 'starts', value: 'ab' }, 'abc', undefined, 'text'), pass({ op: 'ends', value: 'bc' }, 'abc', undefined, 'text'), pass({ op: 'ends', value: 'ab' }, 'abc', undefined, 'text')], [true, true, false])
  expect('a text condition on nothing', pass({ op: 'contains', value: 'a' }, null, undefined, 'text'), false)
  expect('a bill number is text', pass({ op: 'contains', value: '/12' }, '2026-27/12', undefined, 'text'), true)

  // numbers compare as numbers, whatever is shown
  const n = (op, raw, value, value2) => pass({ op, value, value2 }, raw, undefined, 'number')
  expect('gt', [n('gt', 1500, '1000'), n('gt', 900, '1000'), n('gt', 1000, '1000')], [true, false, false])
  expect('gte / lte', [n('gte', 1000, '1000'), n('lte', 1000, '1000'), n('lt', 1000, '1000')], [true, true, false])
  expect('commas typed are ignored', n('gt', 120000, '1,00,000'), true)
  expect('between, either way round and inclusive', [n('between', 5, '3', '9'), n('between', 5, '9', '3'), n('between', 3, '3', '9'), n('between', 10, '3', '9')], [true, true, true, false])
  expect('a number is not text', n('gt', '50', '9'), true) // 50 > 9 as numbers, though "50" < "9" as text
  expect('nothing in a number column passes a comparison', [n('gt', null, '1'), n('eq', '', '0')], [false, false])
  expect('ne passes nothing', n('ne', null, '1'), true)
  expect('a bad number passes nothing', n('gt', 5, 'abc'), false)

  // dates compare as days
  const d = (op, raw, value, value2) => pass({ op, value, value2 }, raw, undefined, 'date')
  expect('dates', [d('gte', '2026-04-01T10:00:00', '2026-04-01'), d('lt', '2026-03-31', '2026-04-01'), d('between', '2026-05-05', '2026-05-01', '2026-05-31')], [true, true, true])

  // empty and picks
  expect('empty', [pass({ op: 'empty' }, '', undefined, 'text'), pass({ op: 'empty' }, null, undefined, 'text'), pass({ op: 'empty' }, 'x', undefined, 'text')], [true, true, false])
  expect('not_empty', pass({ op: 'not_empty' }, 'x', undefined, 'text'), true)
  expect('a pick', [pass({ op: 'in', values: ['Won', 'Open'] }, 'Won', undefined, 'text'), pass({ op: 'in', values: ['Won'] }, 'Lost', undefined, 'text')], [true, false])
  expect('a pick that takes the empty rows', [pass({ op: 'in', values: ['Won'], empty: true }, null, undefined, 'text'), pass({ op: 'in', values: ['Won'] }, null, undefined, 'text')], [true, false])

  // when a filter is complete enough to send
  expect('complete', [f.isComplete({ column: 'c', op: 'contains', value: '' }), f.isComplete({ column: 'c', op: 'contains', value: 'a' }), f.isComplete({ column: 'c', op: 'empty' }), f.isComplete({ column: 'c', op: 'in', values: [] }), f.isComplete({ column: 'c', op: 'in', values: [], empty: true }), f.isComplete({ column: 'c', op: 'between', value: '1' }), f.isComplete({ column: 'c', op: 'between', value: '1', value2: '2' })], [false, true, true, false, true, false, true])
  expect('only complete filters are sent', f.encodeFilters([{ column: 'a', op: 'contains', value: '' }, { column: 'b', op: 'empty' }]), JSON.stringify([{ column: 'b', op: 'empty' }]))
  expect('none are sent as nothing', f.encodeFilters([]), undefined)
  expect('one filter per column', f.setFilter([{ column: 'a', op: 'empty' }], 'a', { column: 'a', op: 'not_empty' }).length, 1)
  expect('an incomplete one removes it', f.setFilter([{ column: 'a', op: 'empty' }], 'a', { column: 'a', op: 'contains', value: '' }).length, 0)
  expect('null removes it', f.setFilter([{ column: 'a', op: 'empty' }, { column: 'b', op: 'empty' }], 'a', null).map((x) => x.column), ['b'])

  // the chip says it in words
  expect('chip: condition', f.describeFilter({ column: 'amount', op: 'gt', value: '5000' }, 'Amount', 'number'), 'Amount is more than 5000')
  expect('chip: between', f.describeFilter({ column: 'a', op: 'between', value: '1', value2: '9' }, 'A', 'number'), 'A is between 1 and 9')
  expect('chip: pick', f.describeFilter({ column: 's', op: 'in', values: ['Won', 'Open', 'Lost', 'Held'], empty: true }, 'Status', 'text'), 'Status is one of Won, Open, Lost, (empty) +1')
  expect('chip: empty', f.describeFilter({ column: 's', op: 'empty' }, 'Status', 'text'), 'Status is empty')

  // the pick list made from rows: most common first, search narrows it, nothing is its own entry
  const rows = [{ s: 'Won' }, { s: 'Open' }, { s: 'Won' }, { s: '' }, { s: 'Lost' }, { s: 'Won' }, { s: 'Open' }]
  expect('values', f.valuesFromRows(rows, 's', '').values, [{ value: 'Won', count: 3 }, { value: 'Open', count: 2 }, { value: 'Lost', count: 1 }, { value: null, count: 1 }])
  expect('values search', f.valuesFromRows(rows, 's', 'op').values, [{ value: 'Open', count: 2 }])
  expect('values are capped', f.valuesFromRows(rows, 's', '', 2).truncated, true)

  // what a column holds, from its rows
  expect('kinds', [f.kindFromRows([{ a: 1 }, { a: '2.5' }], 'a'), f.kindFromRows([{ a: 1 }, { a: 'x' }], 'a'), f.kindFromRows([{ a: null }], 'a'), f.kindFromRows([{ a: true }], 'a')], ['number', 'text', 'text', 'bool'])
} finally {
  rmSync(out, { recursive: true, force: true })
}

if (failures) {
  console.log(`\n${failures} of ${checked} checks failed.`)
  process.exit(1)
}
console.log(`Column filters: all ${checked} checks pass.`)
