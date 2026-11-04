import type { BillFont } from '../types'

/**
 * The typefaces and sizes a printed bill can use. The same keys, labels, stacks and sizes are in backend/app/bill_fonts.py
 * (a test compares them): the screen and the print draw the bill with these, the PDF with the server's copy of the same typeface.
 */
export const FONT_SIZES = [8, 9, 10, 11, 12, 13, 14] as const
/** The size a bill was always printed at, in points. */
export const BASE_SIZE = 9
export const DEFAULT_FONT: BillFont = { family: 'arial', size: BASE_SIZE }

export const FONTS: { key: string; label: string; css: string }[] = [
  { key: 'arial', label: 'Arial', css: 'Arial, "Helvetica Neue", Helvetica, "Liberation Sans", sans-serif' },
  { key: 'calibri', label: 'Calibri', css: 'Calibri, Carlito, "Segoe UI", Arial, sans-serif' },
  { key: 'segoe', label: 'Segoe UI', css: '"Segoe UI", "Nirmala UI", system-ui, Arial, sans-serif' },
  { key: 'tahoma', label: 'Tahoma', css: 'Tahoma, "Segoe UI", Arial, sans-serif' },
  { key: 'verdana', label: 'Verdana', css: 'Verdana, "DejaVu Sans", Geneva, sans-serif' },
  { key: 'trebuchet', label: 'Trebuchet MS', css: '"Trebuchet MS", "Segoe UI", Arial, sans-serif' },
  { key: 'times', label: 'Times New Roman', css: '"Times New Roman", Times, "Liberation Serif", serif' },
  { key: 'georgia', label: 'Georgia', css: 'Georgia, "Times New Roman", serif' },
  { key: 'courier', label: 'Courier New', css: '"Courier New", Courier, "Liberation Mono", monospace' },
]

export const fontCss = (family: string | null | undefined): string => (FONTS.find((f) => f.key === family) ?? FONTS[0]).css

/** The bill's base font size on screen: points to CSS pixels. Everything else on the bill is in em, so it scales with this. */
export const fontPx = (size: number | null | undefined): number => ((size && FONT_SIZES.includes(size as (typeof FONT_SIZES)[number]) ? size : BASE_SIZE) * 4) / 3

export const fontLabel = (font: BillFont): string => `${FONTS.find((f) => f.key === font.family)?.label ?? 'Arial'}, ${font.size} pt`
