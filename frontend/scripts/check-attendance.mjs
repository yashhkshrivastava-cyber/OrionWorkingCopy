/**
 * Checks that the attendance register's live figure agrees with the server's: both must give the amounts in backend/tests/attendance_vectors.json.
 * Run:  cd frontend && npm run check:attendance
 *
 * It bundles src/attendance/attendanceCalc.ts with esbuild (already a dependency of Vite) into a temporary folder.
 */

import { build } from 'esbuild'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const out = mkdtempSync(join(tmpdir(), 'orion-attendance-'))
let failures = 0

try {
  await build({ entryPoints: [resolve(here, '../src/attendance/attendanceCalc.ts')], bundle: true, format: 'esm', platform: 'node', outfile: join(out, 'calc.mjs'), logLevel: 'silent' })
  const { calculatedAmount, daysInMonth } = await import(pathToFileURL(join(out, 'calc.mjs')).href)
  const vectors = JSON.parse(readFileSync(resolve(here, '../../backend/tests/attendance_vectors.json'), 'utf8'))
  for (const v of vectors) {
    const got = calculatedAmount(v.rate, v.days, v.extra, v.deduction)
    if (got !== v.amount) {
      failures += 1
      console.log(`FAIL ${JSON.stringify(v)}\n  got ${got}`)
    }
  }
  for (const [month, days] of [['2026-02', 28], ['2028-02', 29], ['2026-10', 31], ['2026-11', 30]]) {
    if (daysInMonth(month) !== days) {
      failures += 1
      console.log(`FAIL daysInMonth(${month}) = ${daysInMonth(month)}, want ${days}`)
    }
  }
  console.log(failures ? `${failures} failed` : `Attendance arithmetic matches the server on all ${vectors.length} vectors.`)
} finally {
  rmSync(out, { recursive: true, force: true })
}
process.exit(failures ? 1 : 0)
