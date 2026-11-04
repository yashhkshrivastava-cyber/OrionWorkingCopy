/**
 * Checks the theme system without a browser. Run:  cd frontend && npm run check:themes
 *
 *  1. Contrast. Every theme, in both modes, with every style, every accent swatch, a few awkward custom accents and
 *     high-contrast mode, must keep text, accent text, button labels and status colours at WCAG AA (7:1 for body text
 *     on the page and the rail).
 *  2. The Default theme. The stylesheet's `:root` and `.dark` blocks are what the page shows before any script runs,
 *     and the engine's output for Default is what it shows after. They must be the same, or the page would flash.
 *  3. Shape. Every theme and style has what the settings screen and the engine need.
 *
 * It bundles the theme modules with esbuild (already a dependency of Vite) into a temporary folder.
 */

import { build } from 'esbuild'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = resolve(here, '../src')
const out = mkdtempSync(join(tmpdir(), 'orion-themes-'))

let failures = 0
const fail = (message) => {
  failures += 1
  console.log(`FAIL ${message}`)
}

try {
  await build({
    entryPoints: { engine: join(src, 'theme/engine.ts'), themes: join(src, 'theme/themes.ts'), preferences: join(src, 'theme/preferences.ts') },
    bundle: true,
    format: 'esm',
    platform: 'node',
    outdir: out,
    logLevel: 'error',
  })
  const load = (name) => import(pathToFileURL(join(out, `${name}.js`)).href)
  const engine = await load('engine')
  const themes = await load('themes')
  const { DEFAULT_PREFS } = await load('preferences')

  // ------------------------------------------------------------------------------------------------ 1. contrast
  let total = 0
  const run = (label, prefs, mode) => {
    for (const check of engine.checks(prefs, mode)) {
      total += 1
      if (check.ratio < check.min) fail(`${label} (${mode}): ${check.name} is ${check.ratio.toFixed(2)}:1, needs ${check.min}:1`)
    }
  }
  const awkward = ['#ffff00', '#000000', '#ffffff', '#808080', '#00ffff', '#ff00ff', '#7fff00']
  for (const theme of themes.THEMES) {
    for (const mode of ['light', 'dark']) {
      run(theme.id, { ...DEFAULT_PREFS, theme: theme.id }, mode)
      run(`${theme.id} + high contrast`, { ...DEFAULT_PREFS, theme: theme.id, contrast: 'high' }, mode)
      for (const style of themes.STYLES) run(`${theme.id} + ${style.id}`, { ...DEFAULT_PREFS, theme: theme.id, style: style.id }, mode)
      for (const swatch of themes.ACCENT_SWATCHES) run(`${theme.id} + accent ${swatch.name}`, { ...DEFAULT_PREFS, theme: theme.id, accent: swatch.color }, mode)
      for (const accent of awkward) run(`${theme.id} + accent ${accent}`, { ...DEFAULT_PREFS, theme: theme.id, accent }, mode)
    }
  }
  console.log(`contrast: ${total} checks`)

  // ------------------------------------------------------------------- 2. Default theme equals the stylesheet
  const css = readFileSync(join(src, 'index.css'), 'utf8')
  const block = (selector) => {
    const start = css.indexOf(`\n${selector} {`)
    if (start < 0) throw new Error(`index.css has no ${selector} block`)
    const end = css.indexOf('\n}', start)
    return Object.fromEntries([...css.slice(start, end).matchAll(/^\s*(--orion-[a-z0-9-]+):\s*([^;]+);/gm)].map((m) => [m[1], m[2].trim()]))
  }
  const root = block(':root')
  const dark = { ...root, ...block('.dark') }
  const normal = (value) => value.toLowerCase().replace(/\s+/g, ' ').replace(/\s*,\s*/g, ', ')
  // Constants that no theme changes (the chart colours other than the first series, and the fixed "ink" colour), so the
  // engine has no reason to write them.
  const isStatic = (name) => name === '--orion-ink' || (name.startsWith('--orion-s-') && name !== '--orion-s-primary')
  for (const [mode, baseline] of [['light', root], ['dark', dark]]) {
    const resolved = engine.resolveAppearance(DEFAULT_PREFS, mode).vars
    let compared = 0
    for (const [name, value] of Object.entries(baseline)) {
      if (isStatic(name)) continue
      if (!(name in resolved)) {
        fail(`index.css sets ${name} but the engine never does (${mode})`)
        continue
      }
      compared += 1
      if (normal(resolved[name]) !== normal(value)) fail(`Default ${mode}: ${name} is ${resolved[name]} in the engine and ${value} in index.css`)
    }
    console.log(`default ${mode}: ${compared} variables match index.css`)
  }

  // ---------------------------------------------------------------------------------------------------- 3. shape
  const ids = new Set()
  for (const theme of themes.THEMES) {
    if (ids.has(theme.id)) fail(`duplicate theme id ${theme.id}`)
    ids.add(theme.id)
    if (!/^[a-z0-9-]{1,32}$/.test(theme.id)) fail(`theme id ${theme.id} is not a valid name`)
    if (!theme.name || !theme.tagline || !theme.description) fail(`${theme.id} needs a name, tagline and description`)
    if (!themes.STYLES.some((s) => s.id === theme.style)) fail(`${theme.id} names an unknown style ${theme.style}`)
    for (const mode of ['light', 'dark']) {
      for (const key of ['accent', 'accent2', 'secondary']) if (!/^#[0-9a-f]{6}$/i.test(theme[key][mode])) fail(`${theme.id}.${key}.${mode} is not a hex colour`)
      for (const key of ['bg', 'surface', 'text', 'rail']) if (!/^#[0-9a-f]{6}$/i.test(theme.palette[mode][key])) fail(`${theme.id}.palette.${mode}.${key} is not a hex colour`)
    }
  }
  if (themes.THEMES[0].id !== 'default') fail('the first theme must be Default')
  console.log(`themes: ${themes.THEMES.length}, styles: ${themes.STYLES.length}`)
} finally {
  rmSync(out, { recursive: true, force: true })
}

if (failures) {
  console.log(`\n${failures} problem(s)`)
  process.exit(1)
}
console.log('\nAll theme checks passed.')
