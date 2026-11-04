/**
 * Checks the text side of the money fields: the Indian commas, what is kept of what was typed or pasted, and the amount in words.
 * Run:  cd frontend && npm run check:money
 *
 * It bundles src/billing/moneyText.ts with esbuild (already a dependency of Vite) into a temporary folder.
 */

import { build } from 'esbuild'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const out = mkdtempSync(join(tmpdir(), 'orion-money-'))
let failures = 0
let checked = 0
const expect = (what, got, want) => {
  checked += 1
  if (got !== want) {
    failures += 1
    console.log(`FAIL ${what}\n  got  ${JSON.stringify(got)}\n  want ${JSON.stringify(want)}`)
  }
}

try {
  await build({ entryPoints: [resolve(here, '../src/billing/moneyText.ts')], bundle: true, format: 'esm', platform: 'node', outfile: join(out, 'moneyText.mjs'), logLevel: 'silent' })
  const { groupIndian, cleanAmount, showAmount, wordsOfAmount } = await import(pathToFileURL(join(out, 'moneyText.mjs')).href)

  // the commas: the last three digits, then twos
  for (const [digits, want] of [['0', '0'], ['7', '7'], ['999', '999'], ['1000', '1,000'], ['12345', '12,345'], ['100000', '1,00,000'], ['1234567', '12,34,567'], ['12345678', '1,23,45,678'], ['123456789012', '1,23,45,67,89,012']]) {
    expect(`groupIndian(${digits})`, groupIndian(digits), want)
  }

  // what is kept of what is typed
  expect('commas typed back', cleanAmount('1,23,456.50', 2, false), '123456.50')
  expect('pasted with a rupee sign', cleanAmount('₹ 1,00,000', 2, false), '100000')
  expect('letters dropped', cleanAmount('12ab3', 2, false), '123')
  expect('a third decimal is not kept', cleanAmount('1.239', 2, false), '1.23')
  expect('a second point is not kept', cleanAmount('1.2.3', 2, false), '1.23')
  expect('a leading point gets its zero', cleanAmount('.5', 2, false), '0.5')
  expect('leading zeros go', cleanAmount('007', 2, false), '7')
  expect('a point being typed stays', cleanAmount('12.', 2, false), '12.')
  expect('no decimals asked: the point goes', cleanAmount('12.5', 0, false), '12')
  expect('a minus is refused where it cannot be', cleanAmount('-5', 2, false), '5')
  expect('a minus is kept where it can be', cleanAmount('-5', 2, true), '-5')
  expect('a minus anywhere else is not a minus', cleanAmount('5-5', 2, true), '55')
  expect('empty stays empty', cleanAmount('', 2, false), '')

  // what is shown while typing
  expect('showAmount whole', showAmount('1234567'), '12,34,567')
  expect('showAmount with paise', showAmount('1234567.5'), '12,34,567.5')
  expect('showAmount a point being typed', showAmount('1234.'), '1,234.')
  expect('showAmount negative', showAmount('-100000'), '-1,00,000')
  expect('showAmount empty', showAmount(''), '')

  // the words
  const words = (raw, scale) => wordsOfAmount(raw, scale)
  expect('empty has no words', words(''), null)
  expect('a lone minus has no words', words('-'), null)
  expect('zero', words('0'), 'Zero Rupees Only')
  expect('one rupee', words('1'), 'One Rupee Only')
  expect('plain', words('1250'), 'One Thousand Two Hundred Fifty Rupees Only')
  expect('with paise', words('1250.75'), 'One Thousand Two Hundred Fifty Rupees and Seventy Five Paise Only')
  expect('one paisa', words('0.01'), 'One Paisa Only')
  expect('a tenth is ten paise', words('12.5'), 'Twelve Rupees and Fifty Paise Only')
  expect('a point being typed', words('12.'), 'Twelve Rupees Only')
  expect('lakh', words('100000'), 'One Lakh Rupees Only')
  expect('lakh and thousand', words('250000'), 'Two Lakh Fifty Thousand Rupees Only')
  expect('crore', words('10000000'), 'One Crore Rupees Only')
  expect('mixed', words('12345678'), 'One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight Rupees Only')
  expect('a hundred crore', words('1000000000'), 'One Hundred Crore Rupees Only')
  expect('negative', words('-500'), 'Minus Five Hundred Rupees Only')
  expect('a field in lakh', words('2.5', 100000), 'Two Lakh Fifty Thousand Rupees Only')
  expect('a field in lakh, small', words('0.1', 100000), 'Ten Thousand Rupees Only')
  expect('a field in lakh, many decimals', words('12.3456', 100000), 'Twelve Lakh Thirty Four Thousand Five Hundred Sixty Rupees Only')
  expect('thousands of crore, exact', words('99999999999'), 'Nine Thousand Nine Hundred Ninety Nine Crore Ninety Nine Lakh Ninety Nine Thousand Nine Hundred Ninety Nine Rupees Only')
} finally {
  rmSync(out, { recursive: true, force: true })
}

console.log(failures ? `\n${failures} of ${checked} checks failed.` : `Money text: all ${checked} checks pass.`)
process.exit(failures ? 1 : 0)
