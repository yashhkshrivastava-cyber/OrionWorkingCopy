/**
 * The theme engine. `resolveAppearance` is a pure function: (preferences, mode) in, one flat map of CSS variables out.
 * `applyAppearance` writes that map onto <html>. Every component reads the variables (through the Tailwind tokens in
 * index.css), so changing the map re-skins the whole application with no re-render.
 *
 * Contrast is part of the contract, not an afterthought: text colours, the accent used as text, and the text on the
 * accent are all pushed to WCAG AA by `ensureContrast`, whatever seed colours or custom accent they start from.
 */

import { alpha, contrast, ensureContrast, hexToOklch, mix, oklchToHex, rampFrom, readableOn, STEPS } from './color'
import { styleById, themeById } from './themes'
import type {
  AccentTokens,
  AppearancePrefs,
  Density,
  Mode,
  Palette,
  PaletteSeed,
  ResolvedAppearance,
  ShadowLevel,
  StyleDef,
  ThemeDef,
} from './types'

const DENSITY: Record<Density, number> = { compact: 0.9, comfortable: 1, spacious: 1.1 }

// ----------------------------------------------------------------------------------------------------- the palette

const STATUS: Record<Mode, Record<'positive' | 'negative' | 'warning' | 'amber' | 'rose' | 'emerald', string>> = {
  light: { positive: '#0a7a52', negative: '#c42348', warning: '#a86404', amber: '#c27a06', rose: '#dc2f55', emerald: '#0b8a5c' },
  dark: { positive: '#3fd39b', negative: '#fb7691', warning: '#f5b83d', amber: '#f5b83d', rose: '#fb7691', emerald: '#3fd39b' },
}

/** Works out a whole palette from a few seed colours. */
export function derivePalette(seed: PaletteSeed, mode: Mode): Palette {
  const dark = mode === 'dark'
  const { bg, surface, text } = seed
  const weight = seed.borderWeight ?? 1

  const surfaceHover = mix(surface, text, dark ? 0.05 : 0.035)
  const muted = seed.muted ?? mix(surface, text, dark ? 0.065 : 0.05)
  const border = seed.border ?? mix(surface, text, (dark ? 0.12 : 0.11) * weight)
  const borderStrong = seed.borderStrong ?? mix(surface, text, (dark ? 0.25 : 0.24) * weight)

  // Secondary and faint text must read on the page, the card and the tinted panels, whichever is furthest from the
  // text colour. Even the faintest text reaches 4.5:1, because the interface uses it for small labels and captions.
  const worst = (fg: string, min: number) => [bg, surface, muted, surfaceHover].reduce((color, back) => ensureContrast(color, back, min), fg)
  const textMuted = seed.textMuted ?? worst(mix(text, surface, 0.34), 4.6)
  const textFaint = seed.textFaint ?? worst(mix(text, surface, 0.5), 4.5)

  const lightRail = hexToOklch(seed.rail).l > 0.6
  const ink = lightRail ? '#000000' : '#ffffff'
  const railStrong = lightRail ? mix(seed.rail, '#000000', 0.88) : '#ffffff'
  const railText = ensureContrast(mix(railStrong, seed.rail, lightRail ? 0.3 : 0.26), seed.rail, 7)
  const railTextFaint = ensureContrast(mix(railStrong, seed.rail, 0.55), seed.rail, 4.5)

  // A status colour is used as text on the plain surface and on its own tint (a "Due soon" chip), so it must read on both.
  const dimOf = (key: keyof typeof STATUS.light) => mix(surface, STATUS[mode][key], dark ? 0.17 : 0.1)
  const status = (key: keyof typeof STATUS.light) => ensureContrast(ensureContrast(STATUS[mode][key], surface, 4.5), dimOf(key), 4.5)

  return {
    bg,
    bgElevated: surface,
    surface,
    surfaceHover,
    muted,
    border,
    borderStrong,
    text,
    textMuted,
    textFaint,
    rail: seed.rail,
    railRaised: mix(seed.rail, ink, 0.05),
    railBorder: mix(seed.rail, ink, lightRail ? 0.1 : 0.09),
    railText,
    railTextFaint,
    railStrong,
    railHover: alpha(railStrong, 0.06),
    railActive: alpha(railStrong, lightRail ? 0.09 : 0.1),
    chartTick: ensureContrast(mix(text, bg, 0.4), surface, 3.6),
    chartGrid: mix(surface, text, dark ? 0.09 : 0.07),
    chartCursor: alpha(text, 0.09),
    positive: status('positive'),
    positiveDim: dimOf('positive'),
    negative: status('negative'),
    negativeDim: dimOf('negative'),
    warning: status('warning'),
    warningDim: dimOf('warning'),
    amber: STATUS[mode].amber,
    rose: STATUS[mode].rose,
    emerald: STATUS[mode].emerald,
  }
}

/** Borders get stronger or softer with the style, without touching the rest of the palette. */
function weighBorders(p: Palette, weight: number): Palette {
  if (weight === 1) return p
  if (weight < 1) {
    return { ...p, border: mix(p.surface, p.border, weight), borderStrong: mix(p.surface, p.borderStrong, Math.max(weight, 0.5)) }
  }
  const k = Math.min(weight - 1, 1)
  return { ...p, border: mix(p.border, p.borderStrong, k), borderStrong: mix(p.borderStrong, p.text, k * 0.3) }
}

/** More contrast for people who need it: text moves toward the extreme, borders become visible. */
function withHighContrast(p: Palette, mode: Mode): Palette {
  const extreme = mode === 'dark' ? '#ffffff' : '#000000'
  const text = mix(p.text, extreme, 0.4)
  const textMuted = ensureContrast(mix(p.textMuted, text, 0.55), p.surface, 7)
  const textFaint = ensureContrast(mix(p.textFaint, text, 0.6), p.surface, 5.5)
  return {
    ...p,
    text,
    textMuted,
    textFaint,
    border: p.borderStrong,
    borderStrong: mix(p.borderStrong, text, 0.45),
    chartTick: ensureContrast(p.chartTick, p.surface, 4.5),
  }
}

// ------------------------------------------------------------------------------------------------------ the accent

/** A chart-friendly version of the accent: same hue, lightness held to the range that reads on light and dark surfaces. */
function seriesFrom(accent: string): string {
  const c = hexToOklch(accent)
  return oklchToHex({ l: Math.min(0.74, Math.max(0.6, c.l)), c: Math.max(c.c, 0.06), h: c.h })
}

/** Everything that follows from one accent colour, checked against the palette it sits on. */
export function deriveAccent(accent: string, accent2: string, secondary: string, palette: Palette, mode: Mode): AccentTokens {
  const dark = mode === 'dark'
  const onPrimary = readableOn(accent)
  // Move the fill, not the text, until the label on the button reads at AA.
  const primary = ensureContrast(accent, onPrimary, 4.5)
  const primaryHover = onPrimary === '#ffffff' ? mix(primary, '#000000', 0.14) : mix(primary, '#ffffff', 0.14)
  const accentDim = mix(palette.surface, accent, dark ? 0.2 : 0.12)
  const secondaryDim = mix(palette.surface, secondary, dark ? 0.2 : 0.12)
  // Accent text sits on the surface, the page and its own tint (a selected row, a chip), so it must read on all three.
  const text = (c: string, dim: string) => [palette.surface, palette.bg, dim].reduce((color, back) => ensureContrast(color, back, 4.5), c)
  return {
    ramp: rampFrom(accent),
    secondaryRamp: rampFrom(secondary),
    primary,
    primaryHover,
    onPrimary,
    accent: text(accent, accentDim),
    accentDim,
    secondary: text(secondary, secondaryDim),
    secondaryDim,
    gradientFrom: primary,
    gradientTo: ensureContrast(accent2, onPrimary, 4.5),
  }
}

/** A second accent for gradients when the person chose only one colour: the same colour, turned a little round the wheel. */
function companionOf(accent: string): string {
  const c = hexToOklch(accent)
  return oklchToHex({ l: c.l, c: c.c, h: (c.h + 38) % 360 })
}

// ------------------------------------------------------------------------------------------------ shadows and light

function shadows(level: ShadowLevel, mode: Mode, standard: { card: string; raised: string; overlay: string }) {
  const ink = mode === 'dark' ? '0 0 0' : '14 23 38'
  const k = mode === 'dark' ? 1 : 0.55
  const a = (n: number) => Math.round(n * k * 1000) / 1000
  switch (level) {
    case 'none':
      return { card: 'none', raised: `0 6px 18px -10px rgb(${ink} / ${a(0.3)})`, overlay: `0 18px 44px -18px rgb(${ink} / ${a(0.5)})` }
    case 'soft':
      return {
        card: `0 1px 2px rgb(${ink} / ${a(0.1)}), 0 6px 18px -8px rgb(${ink} / ${a(0.2)})`,
        raised: `0 16px 36px -16px rgb(${ink} / ${a(0.4)})`,
        overlay: `0 32px 64px -24px rgb(${ink} / ${a(0.55)})`,
      }
    case 'hard':
      return {
        card: `0 1px 0 rgb(${ink} / ${a(0.22)}), 0 2px 8px -2px rgb(${ink} / ${a(0.32)})`,
        raised: `0 10px 22px -8px rgb(${ink} / ${a(0.55)})`,
        overlay: `0 24px 48px -12px rgb(${ink} / ${a(0.7)})`,
      }
    case 'dramatic':
      return {
        card: `0 1px 2px rgb(${ink} / ${a(0.55)}), 0 12px 30px -14px rgb(${ink} / ${a(0.75)})`,
        raised: `0 24px 50px -18px rgb(${ink} / ${a(0.85)})`,
        overlay: `0 40px 90px -26px rgb(${ink} / ${a(0.95)})`,
      }
    default:
      return standard
  }
}

const STANDARD_SHADOWS: Record<Mode, { card: string; raised: string; overlay: string }> = {
  light: {
    card: '0 1px 2px rgb(14 23 38 / 0.04), 0 1px 1px rgb(14 23 38 / 0.03)',
    raised: '0 10px 24px -12px rgb(14 23 38 / 0.18), 0 2px 6px -2px rgb(14 23 38 / 0.06)',
    overlay: '0 24px 48px -16px rgb(14 23 38 / 0.28), 0 4px 12px -4px rgb(14 23 38 / 0.1)',
  },
  dark: {
    card: '0 1px 2px rgb(0 0 0 / 0.3)',
    raised: '0 12px 28px -14px rgb(0 0 0 / 0.7), 0 2px 6px -2px rgb(0 0 0 / 0.4)',
    overlay: '0 28px 56px -18px rgb(0 0 0 / 0.8), 0 6px 14px -6px rgb(0 0 0 / 0.5)',
  },
}

// --------------------------------------------------------------------------------------------------------- resolve

/** The theme and style a set of preferences lands on, after the person's own choices are laid over the theme's. */
export function describe(prefs: AppearancePrefs): { theme: ThemeDef; style: StyleDef } {
  const theme = themeById(prefs.theme)
  const style = styleById(prefs.style ?? theme.style)
  return { theme, style }
}

export function systemMode(): Mode {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function modeOf(prefs: AppearancePrefs): Mode {
  return prefs.mode === 'system' ? systemMode() : prefs.mode
}

export function resolveAppearance(prefs: AppearancePrefs, mode: Mode): ResolvedAppearance {
  const { theme, style } = describe(prefs)
  const dark = mode === 'dark'

  let palette = theme.exact?.palette?.[mode] ?? derivePalette(theme.palette[mode], mode)
  palette = weighBorders(palette, style.borderWeight)
  if (prefs.contrast === 'high') palette = withHighContrast(palette, mode)

  const custom = prefs.accent !== null
  const tokens: AccentTokens =
    !custom && theme.exact?.accent
      ? theme.exact.accent[mode]
      : deriveAccent(
          prefs.accent ?? theme.accent[mode],
          custom ? companionOf(prefs.accent!) : theme.accent2[mode],
          theme.secondary[mode],
          palette,
          mode,
        )

  const gradient = prefs.gradient ?? style.gradient
  const ambient = prefs.ambient ?? style.ambient
  const radius = prefs.radius ?? theme.radius ?? style.radius
  const alphaFill = style.surfaceAlpha[mode]
  const sh = shadows(style.shadow, mode, STANDARD_SHADOWS[mode])
  const glow = style.glow
  const wash = style.ambientStrength

  const v: Record<string, string> = {}

  // Surfaces, text and the rail.
  v['--orion-bg'] = palette.bg
  v['--orion-bg-elevated'] = palette.bgElevated
  v['--orion-surface'] = palette.surface
  v['--orion-surface-hover'] = palette.surfaceHover
  v['--orion-muted'] = palette.muted
  v['--orion-border'] = palette.border
  v['--orion-border-strong'] = palette.borderStrong
  v['--orion-text'] = palette.text
  v['--orion-text-muted'] = palette.textMuted
  v['--orion-text-faint'] = palette.textFaint
  v['--orion-rail'] = palette.rail
  v['--orion-rail-raised'] = palette.railRaised
  v['--orion-rail-border'] = palette.railBorder
  v['--orion-rail-text'] = palette.railText
  v['--orion-rail-text-faint'] = palette.railTextFaint
  v['--orion-rail-strong'] = palette.railStrong
  v['--orion-rail-hover'] = palette.railHover
  v['--orion-rail-active'] = palette.railActive
  v['--orion-chart-tick'] = palette.chartTick
  v['--orion-chart-grid'] = palette.chartGrid
  v['--orion-chart-cursor'] = palette.chartCursor

  // Status colours.
  v['--orion-positive'] = palette.positive
  v['--orion-positive-dim'] = palette.positiveDim
  v['--orion-negative'] = palette.negative
  v['--orion-negative-dim'] = palette.negativeDim
  v['--orion-warning'] = palette.warning
  v['--orion-warning-dim'] = palette.warningDim
  v['--orion-on-negative'] = readableOn(palette.negative)
  v['--orion-scrim'] = alpha(mix(palette.bg, '#000000', dark ? 0.7 : 0.78), dark ? 0.68 : 0.52)
  v['--orion-amber'] = palette.amber
  v['--orion-rose'] = palette.rose
  v['--orion-emerald'] = palette.emerald

  // The accent, its ramps, and the primary action.
  STEPS.forEach((step) => {
    v[`--orion-brand-${step}`] = tokens.ramp[step]
    v[`--orion-alt-${step}`] = tokens.secondaryRamp[step]
  })
  v['--orion-accent'] = tokens.accent
  v['--orion-accent-dim'] = tokens.accentDim
  v['--orion-violet'] = tokens.secondary
  v['--orion-violet-dim'] = tokens.secondaryDim
  v['--orion-rail-accent'] = ensureContrast(tokens.ramp[300], palette.rail, 4.5)
  // The logo: from the accent's deep end to the secondary hue's. Default keeps the original teal-to-navy.
  v['--orion-mark-from'] = !custom && theme.exact?.accent ? '#0f766e' : tokens.ramp[700]
  v['--orion-mark-mid'] = !custom && theme.exact?.accent ? '#155e75' : mix(tokens.ramp[700], tokens.secondaryRamp[800], 0.5)
  v['--orion-mark-to'] = !custom && theme.exact?.accent ? '#1e3a8a' : tokens.secondaryRamp[800]
  v['--orion-primary'] = tokens.primary
  // The first chart series is the accent, at a mid lightness so it reads on any surface. Default keeps its own teal.
  v['--orion-s-primary'] = !custom && theme.exact?.accent ? '#16a79d' : seriesFrom(prefs.accent ?? theme.accent[mode])
  v['--orion-primary-hover'] = tokens.primaryHover
  v['--orion-on-primary'] = tokens.onPrimary
  v['--orion-primary-fill'] = gradient
    ? `linear-gradient(135deg, ${tokens.gradientFrom}, ${tokens.gradientTo})`
    : `linear-gradient(${tokens.primary}, ${tokens.primary})`
  v['--orion-primary-fill-hover'] = gradient
    ? `linear-gradient(135deg, ${tokens.primaryHover}, ${mix(tokens.gradientTo, dark ? '#ffffff' : '#000000', 0.1)})`
    : `linear-gradient(${tokens.primaryHover}, ${tokens.primaryHover})`
  v['--orion-highlight-fill'] = gradient
    ? `linear-gradient(135deg, ${tokens.gradientFrom}, ${tokens.gradientTo})`
    : `linear-gradient(${tokens.accent}, ${tokens.accent})`
  v['--orion-ring'] = alpha(tokens.accent, dark ? 0.5 : 0.4)
  v['--orion-ring-width'] = prefs.contrast === 'high' ? '3px' : '2px'
  // Selected text: a tint from the accent ramp, with the page's own text colour (or the ramp's lightest step) on it.
  v['--orion-selection'] = dark ? tokens.ramp[800] : tokens.ramp[200]
  v['--orion-on-selection'] = dark ? tokens.ramp[50] : palette.text

  // Surface treatment: radius, glass, shadows, glow, ambient light.
  v['--orion-radius-scale'] = String(Math.round(radius * 2 * 1000) / 1000)
  v['--orion-surface-fill'] =
    alphaFill >= 1 ? 'var(--orion-surface)' : `color-mix(in srgb, var(--orion-surface) ${Math.round(alphaFill * 100)}%, transparent)`
  v['--orion-backdrop'] = style.blur > 0 ? `blur(${style.blur}px) saturate(1.4)` : 'none'
  v['--orion-shadow-card'] = sh.card
  v['--orion-shadow-raised'] = sh.raised
  v['--orion-shadow-overlay'] = sh.overlay
  v['--orion-glow'] = glow > 0 ? `0 0 0 1px ${alpha(tokens.primary, 0.3 * glow + 0.1)}, 0 0 28px -6px ${alpha(tokens.primary, 0.55 * glow)}` : '0 0 #0000'
  v['--orion-ambient'] = ambient
    ? [
        `radial-gradient(62rem 40rem at 6% -12%, ${alpha(tokens.primary, (dark ? 0.17 : 0.11) * wash)}, transparent 62%)`,
        `radial-gradient(50rem 34rem at 98% -8%, ${alpha(tokens.gradientTo, (dark ? 0.13 : 0.09) * wash)}, transparent 60%)`,
        `radial-gradient(44rem 30rem at 55% 112%, ${alpha(tokens.secondary, (dark ? 0.08 : 0.05) * wash)}, transparent 60%)`,
      ].join(', ')
    : 'none'

  // Density and size.
  v['--spacing'] = `${0.25 * DENSITY[prefs.density]}rem`
  v['--orion-ui-scale'] = String(prefs.scale)

  // Type.
  v['--orion-font-sans'] = theme.fonts.sans
  v['--orion-font-display'] = theme.fonts.display
  v['--orion-display-weight'] = String(theme.fonts.displayWeight)
  v['--orion-display-tracking'] = theme.fonts.displayTracking

  // Motion.
  const reduced = prefs.motion === 'reduced'
  const crisp = theme.motion === 'crisp'
  v['--orion-ease'] = crisp ? 'cubic-bezier(0.2, 0.8, 0.2, 1)' : 'cubic-bezier(0.22, 1, 0.36, 1)'
  v['--orion-dur-fast'] = reduced ? '0ms' : crisp ? '100ms' : '140ms'
  v['--orion-dur-base'] = reduced ? '0ms' : crisp ? '160ms' : '220ms'
  v['--orion-dur-slow'] = reduced ? '0ms' : crisp ? '260ms' : '380ms'

  return {
    mode,
    vars: v,
    themeColor: palette.bg,
    fontLink: theme.fonts.link ?? null,
  }
}

/** The contrast the engine promises, for tests and for the settings screen to show. */
export function checks(prefs: AppearancePrefs, mode: Mode): { name: string; ratio: number; min: number }[] {
  const { vars } = resolveAppearance(prefs, mode)
  const hex = (name: string) => vars[name]
  const surface = hex('--orion-surface')
  const bg = hex('--orion-bg')
  const pair = (name: string, fg: string, back: string, min: number) => ({ name, ratio: contrast(hex(fg), hex(back)), min })
  return [
    pair('text on surface', '--orion-text', '--orion-surface', 7),
    pair('text on page', '--orion-text', '--orion-bg', 7),
    pair('muted text on surface', '--orion-text-muted', '--orion-surface', 4.5),
    pair('muted text on page', '--orion-text-muted', '--orion-bg', 4.5),
    pair('faint text on surface', '--orion-text-faint', '--orion-surface', 4.5),
    pair('faint text on page', '--orion-text-faint', '--orion-bg', 4.5),
    pair('faint text on tinted panels', '--orion-text-faint', '--orion-muted', 4.5),
    pair('accent on surface', '--orion-accent', '--orion-surface', 4.5),
    pair('accent on page', '--orion-accent', '--orion-bg', 4.5),
    pair('accent on its tint', '--orion-accent', '--orion-accent-dim', 4.5),
    pair('secondary on its tint', '--orion-violet', '--orion-violet-dim', 4.5),
    pair('positive on its tint', '--orion-positive', '--orion-positive-dim', 4.5),
    pair('negative on its tint', '--orion-negative', '--orion-negative-dim', 4.5),
    pair('warning on its tint', '--orion-warning', '--orion-warning-dim', 4.5),
    pair('label on primary button', '--orion-on-primary', '--orion-primary', 4.5),
    pair('rail text on rail', '--orion-rail-text', '--orion-rail', 7),
    pair('faint rail text on rail', '--orion-rail-text-faint', '--orion-rail', 4.5),
    pair('positive on surface', '--orion-positive', '--orion-surface', 4.5),
    pair('negative on surface', '--orion-negative', '--orion-surface', 4.5),
    pair('warning on surface', '--orion-warning', '--orion-surface', 4.5),
    { name: 'chart labels on surface', ratio: contrast(hex('--orion-chart-tick'), surface), min: 3.5 },
    { name: 'surface against page', ratio: contrast(surface, bg), min: 1 },
  ]
}
