/**
 * Colour maths for the theme engine: hex <-> OKLCH, mixing, WCAG contrast, and building a whole 50-950 ramp from one
 * accent colour. Everything here is pure and has no dependency, so a theme can be described with a few hex values and
 * the engine works out the rest (tints, hover states, readable text on top of a colour).
 *
 * OKLCH is used instead of HSL because equal steps in its lightness look equal to the eye, so a ramp built from any
 * accent has an even rhythm and a readable text colour is easy to find.
 */

export type RGB = [number, number, number]

const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v))

export function hexToRgb(hex: string): RGB {
  let h = hex.trim().replace('#', '')
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  const n = parseInt(h.slice(0, 6), 16)
  if (Number.isNaN(n)) return [0, 0, 0]
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

export function rgbToHex([r, g, b]: RGB): string {
  const part = (v: number) => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, '0')
  return `#${part(r)}${part(g)}${part(b)}`
}

const toLinear = (c: number) => {
  const v = c / 255
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
}
const fromLinear = (v: number) => 255 * (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055)

export type OKLCH = { l: number; c: number; h: number }

export function rgbToOklch(rgb: RGB): OKLCH {
  const [r, g, b] = rgb.map(toLinear)
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s
  const c = Math.hypot(A, B)
  let h = (Math.atan2(B, A) * 180) / Math.PI
  if (h < 0) h += 360
  return { l: L, c, h }
}

/** The colour as sRGB, or null when it falls outside the sRGB gamut. */
function oklchToRgbRaw({ l, c, h }: OKLCH): RGB | null {
  const a = c * Math.cos((h * Math.PI) / 180)
  const b = c * Math.sin((h * Math.PI) / 180)
  const l_ = l + 0.3963377774 * a + 0.2158037573 * b
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b
  const s_ = l - 0.0894841775 * a - 1.291485548 * b
  const L = l_ ** 3
  const M = m_ ** 3
  const S = s_ ** 3
  const lin: RGB = [
    4.0767416621 * L - 3.3077115913 * M + 0.2309699292 * S,
    -1.2684380046 * L + 2.6097574011 * M - 0.3413193965 * S,
    -0.0041960863 * L - 0.7034186147 * M + 1.707614701 * S,
  ]
  const eps = 0.0005
  if (lin.some((v) => v < -eps || v > 1 + eps)) return null
  return [fromLinear(clamp(lin[0])), fromLinear(clamp(lin[1])), fromLinear(clamp(lin[2]))]
}

/** An OKLCH colour as hex, lowering its chroma until it fits in sRGB so the hue and lightness are kept. */
export function oklchToHex(color: OKLCH): string {
  const l = clamp(color.l)
  let lo = 0
  let hi = color.c
  let best = oklchToRgbRaw({ l, c: 0, h: color.h }) ?? ([l * 255, l * 255, l * 255] as RGB)
  if (oklchToRgbRaw({ l, c: hi, h: color.h })) return rgbToHex(oklchToRgbRaw({ l, c: hi, h: color.h })!)
  for (let i = 0; i < 18; i += 1) {
    const mid = (lo + hi) / 2
    const rgb = oklchToRgbRaw({ l, c: mid, h: color.h })
    if (rgb) {
      best = rgb
      lo = mid
    } else hi = mid
  }
  return rgbToHex(best)
}

export const hexToOklch = (hex: string): OKLCH => rgbToOklch(hexToRgb(hex))

/** Mix two hex colours in OKLab, `t` being the share of `b` (0 gives a, 1 gives b). Better than sRGB: no muddy middles. */
export function mix(a: string, b: string, t: number): string {
  const ca = hexToOklch(a)
  const cb = hexToOklch(b)
  const lab = (c: OKLCH) => ({ L: c.l, A: c.c * Math.cos((c.h * Math.PI) / 180), B: c.c * Math.sin((c.h * Math.PI) / 180) })
  const x = lab(ca)
  const y = lab(cb)
  const L = x.L + (y.L - x.L) * t
  const A = x.A + (y.A - x.A) * t
  const B = x.B + (y.B - x.B) * t
  let h = (Math.atan2(B, A) * 180) / Math.PI
  if (h < 0) h += 360
  return oklchToHex({ l: L, c: Math.hypot(A, B), h })
}

/** A colour with transparency, as the space-separated rgb() form every modern browser takes. */
export function alpha(hex: string, a: number): string {
  const [r, g, b] = hexToRgb(hex)
  return `rgb(${r} ${g} ${b} / ${Math.round(clamp(a) * 1000) / 1000})`
}

export function luminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map(toLinear)
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

/** WCAG contrast ratio between two hex colours, from 1 to 21. */
export function contrast(a: string, b: string): number {
  const la = luminance(a)
  const lb = luminance(b)
  const [hi, lo] = la > lb ? [la, lb] : [lb, la]
  return (hi + 0.05) / (lo + 0.05)
}

/**
 * The colour nearest to `fg` (same hue, same chroma where it can) that reaches `min` contrast against `bg`, found by
 * moving its lightness away from the background. Returns `fg` unchanged when it already passes.
 */
export function ensureContrast(fg: string, bg: string, min: number): string {
  if (contrast(fg, bg) >= min) return fg
  const c = hexToOklch(fg)
  const towardLight = luminance(bg) < 0.4
  for (let step = 1; step <= 60; step += 1) {
    const l = clamp(c.l + (towardLight ? 1 : -1) * step * 0.012)
    const next = oklchToHex({ l, c: c.c, h: c.h })
    if (contrast(next, bg) >= min) return next
    if (l <= 0 || l >= 1) break
  }
  return towardLight ? '#ffffff' : '#000000'
}

const INK = '#0b1220'

/** The text colour (near-white or near-black) that is easier to read on `bg`. */
export function readableOn(bg: string): string {
  return contrast('#ffffff', bg) >= contrast(INK, bg) ? '#ffffff' : INK
}

export const STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950] as const
export type Step = (typeof STEPS)[number]
export type Ramp = Record<Step, string>

// Lightness of each step on a typical hue (OKLCH L), and how much of the accent's chroma it keeps. Step 600 is
// where the accent itself sits; the rest is stretched between white and a deep shade around it.
const LIGHTNESS = [0.975, 0.945, 0.89, 0.82, 0.74, 0.66, 0.58, 0.5, 0.43, 0.36, 0.26]
const CHROMA = [0.1, 0.2, 0.42, 0.64, 0.84, 0.96, 1, 0.98, 0.86, 0.74, 0.58]

/** A 50-950 ramp whose 600 step is `accent`. The ends are tints and shades of the same hue. */
export function rampFrom(accent: string): Ramp {
  const base = hexToOklch(accent)
  const anchor = LIGHTNESS[6]
  const out = {} as Ramp
  STEPS.forEach((step, i) => {
    let l: number
    if (i === 6) l = base.l
    else if (i < 6) l = base.l + ((LIGHTNESS[i] - anchor) * (0.975 - base.l)) / (0.975 - anchor)
    else l = base.l - ((anchor - LIGHTNESS[i]) * (base.l - 0.2)) / (anchor - 0.26)
    out[step] = oklchToHex({ l: clamp(l, 0.12, 0.985), c: base.c * CHROMA[i], h: base.h })
  })
  return out
}
