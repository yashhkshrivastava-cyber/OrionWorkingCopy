import { useMemo, type CSSProperties } from 'react'
import { resolveAppearance } from '../../theme/engine'
import { DEFAULT_PREFS } from '../../theme/preferences'
import type { AppearancePrefs, Mode } from '../../theme/types'

/**
 * A miniature of the real interface, drawn with one theme's variables instead of the page's. The variables are set on
 * this element only (CSS custom properties are inherited, so everything inside resolves against them), which means the
 * card shows exactly what the theme will look like without applying it. It is decorative: the card around it carries
 * the accessible name.
 *
 * Sizes are in pixels on purpose: a thumbnail should not grow when the person raises the interface size.
 */
export function ThemePreview({
  prefs,
  mode,
  className = '',
}: {
  prefs: Partial<AppearancePrefs>
  mode: Mode
  className?: string
}) {
  const vars = useMemo(() => {
    const merged: AppearancePrefs = { ...DEFAULT_PREFS, ...prefs }
    return resolveAppearance(merged, mode).vars
  }, [prefs, mode])

  const root: CSSProperties = {
    ...(vars as CSSProperties),
    backgroundColor: 'var(--orion-bg)',
    backgroundImage: 'var(--orion-ambient)',
    fontFamily: 'var(--orion-font-sans)',
    color: 'var(--orion-text)',
    colorScheme: mode,
  }
  const display: CSSProperties = { fontFamily: 'var(--orion-font-display)', fontWeight: 'var(--orion-display-weight)' as unknown as number, letterSpacing: 'var(--orion-display-tracking)' }
  const radius = (px: number) => `calc(${px}px * var(--orion-radius-scale))`

  if (prefs.experience === 'lumen') return <LumenMiniature root={root} className={className} display={display} radius={radius} />

  return (
    <div aria-hidden="true" className={`relative aspect-[16/10] w-full select-none overflow-hidden ${className}`} style={root}>
      {/* The rail */}
      <div className="absolute inset-y-0 left-0 flex w-[17%] flex-col gap-[5px] px-[6px] py-[7px]" style={{ background: 'var(--orion-rail)', borderRight: '1px solid var(--orion-rail-border)' }}>
        <span className="mb-[4px] block h-[9px] w-[9px] rounded-[3px]" style={{ background: 'var(--orion-highlight-fill)' }} />
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className="relative block h-[7px] rounded-[2px]"
            style={{ background: i === 1 ? 'var(--orion-rail-active)' : 'transparent', borderLeft: i === 1 ? '2px solid var(--orion-rail-accent)' : '2px solid transparent' }}
          >
            <span className="absolute inset-y-[2px] left-[4px] rounded-full" style={{ width: i === 1 ? '56%' : `${44 + i * 8}%`, background: i === 1 ? 'var(--orion-rail-strong)' : 'var(--orion-rail-text-faint)', opacity: i === 1 ? 0.9 : 0.55 }} />
          </span>
        ))}
      </div>

      {/* The page */}
      <div className="absolute inset-y-0 left-[17%] right-0 flex flex-col gap-[6px] p-[8px]">
        <div className="flex items-center justify-between">
          <span style={{ ...display, fontSize: 10, lineHeight: 1 }}>Overview</span>
          <span
            className="btn-primary inline-flex items-center px-[7px] py-[3px]"
            style={{ fontSize: 6.5, fontWeight: 600, lineHeight: 1, borderRadius: radius(5) }}
          >
            Upload
          </span>
        </div>

        <div className="grid grid-cols-2 gap-[6px]">
          {[
            { label: 'Revenue', value: '₹4.2 Cr', bars: [40, 62, 48, 80, 66, 92] },
            { label: 'Expiring', value: '12', bars: [70, 52, 60, 38, 44, 30] },
          ].map((card) => (
            <div key={card.label} className="panel flex flex-col gap-[3px] p-[6px]" style={{ borderRadius: radius(7) }}>
              <span style={{ fontSize: 6, color: 'var(--orion-text-muted)' }}>{card.label}</span>
              <span style={{ ...display, fontSize: 11, lineHeight: 1 }}>{card.value}</span>
              <span className="flex h-[10px] items-end gap-[2px]">
                {card.bars.map((h, i) => (
                  <span key={i} className="block w-[5px] rounded-[1px]" style={{ height: `${h}%`, background: i === card.bars.length - 1 ? 'var(--orion-s-primary)' : 'color-mix(in srgb, var(--orion-s-primary) 38%, transparent)' }} />
                ))}
              </span>
            </div>
          ))}
        </div>

        <div className="panel flex flex-1 flex-col justify-center gap-[4px] px-[7px] py-[5px]" style={{ borderRadius: radius(7) }}>
          {[
            { w: '78%', c: 'var(--orion-s-primary)' },
            { w: '54%', c: 'var(--orion-s-info)' },
            { w: '34%', c: 'var(--orion-s-warn)' },
          ].map((row, i) => (
            <span key={i} className="flex items-center gap-[4px]">
              <span className="block h-[3px] w-[18px] rounded-full" style={{ background: 'var(--orion-border-strong)' }} />
              <span className="block h-[4px] rounded-full" style={{ width: row.w, background: row.c }} />
            </span>
          ))}
          <span className="mt-[1px] flex gap-[4px]">
            <span className="inline-flex px-[5px] py-[2px]" style={{ fontSize: 5.5, lineHeight: 1, fontWeight: 600, background: 'var(--orion-positive-dim)', color: 'var(--orion-positive)', borderRadius: 99 }}>Active</span>
            <span className="inline-flex px-[5px] py-[2px]" style={{ fontSize: 5.5, lineHeight: 1, fontWeight: 600, background: 'var(--orion-warning-dim)', color: 'var(--orion-warning)', borderRadius: 99 }}>Due soon</span>
            <span className="inline-flex px-[5px] py-[2px]" style={{ fontSize: 5.5, lineHeight: 1, fontWeight: 600, background: 'var(--orion-accent-dim)', color: 'var(--orion-accent)', borderRadius: 99 }}>Draft</span>
          </span>
        </div>
      </div>
    </div>
  )
}

/** The Lumen interface in miniature: a floating dock, a search pill, a greeting and soft cards with a glow behind them. */
function LumenMiniature({ root, className, display, radius }: { root: CSSProperties; className: string; display: CSSProperties; radius: (px: number) => string }) {
  return (
    <div aria-hidden="true" className={`relative aspect-[16/10] w-full select-none overflow-hidden ${className}`} style={root}>
      <div className="absolute left-[3%] top-[8%] bottom-[8%] flex w-[8%] flex-col items-center gap-[5px] py-[6px]" style={{ background: 'var(--orion-surface-fill)', border: '1px solid var(--orion-border)', borderRadius: radius(9), boxShadow: 'var(--orion-shadow-raised)' }}>
        <span className="block h-[8px] w-[8px] rounded-full" style={{ background: 'var(--orion-highlight-fill)' }} />
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className="block h-[7px] w-[7px]" style={{ borderRadius: radius(3), background: i === 1 ? 'var(--orion-primary-fill)' : 'var(--orion-border-strong)', opacity: i === 1 ? 1 : 0.7 }} />
        ))}
      </div>
      <div className="absolute inset-y-0 left-[14%] right-[3%] flex flex-col gap-[6px] py-[7px]">
        <div className="flex items-center gap-[6px]">
          <span className="flex-1 truncate" style={{ ...display, fontSize: 10, lineHeight: 1 }}>Good morning</span>
          <span className="inline-flex h-[10px] w-[34%] items-center px-[5px]" style={{ background: 'var(--orion-surface-fill)', border: '1px solid var(--orion-border)', borderRadius: 99, fontSize: 5, color: 'var(--orion-text-faint)' }}>Search</span>
          <span className="block h-[10px] w-[10px] rounded-full" style={{ background: 'var(--orion-primary-fill)' }} />
        </div>
        <div className="grid grid-cols-3 gap-[5px]">
          {['var(--orion-primary-fill)', 'var(--orion-surface-fill)', 'var(--orion-surface-fill)'].map((fill, i) => (
            <div key={i} className="flex flex-col gap-[3px] p-[5px]" style={{ background: fill, border: i ? '1px solid var(--orion-border)' : 'none', borderRadius: radius(9), boxShadow: 'var(--orion-shadow-card)' }}>
              <span className="block h-[3px] w-[40%] rounded-full" style={{ background: i ? 'var(--orion-text-faint)' : 'var(--orion-on-primary)', opacity: 0.6 }} />
              <span style={{ ...display, fontSize: 10, lineHeight: 1, color: i ? 'var(--orion-text)' : 'var(--orion-on-primary)' }}>{['12', '₹4.2L', '3'][i]}</span>
            </div>
          ))}
        </div>
        <div className="flex flex-1 flex-col justify-center gap-[4px] px-[7px] py-[5px]" style={{ background: 'var(--orion-surface-fill)', border: '1px solid var(--orion-border)', borderRadius: radius(11), boxShadow: 'var(--orion-shadow-card)' }}>
          {[78, 54, 36].map((w, i) => (
            <span key={i} className="flex items-center gap-[4px]">
              <span className="block h-[6px] w-[6px] rounded-full" style={{ background: i === 0 ? 'var(--orion-s-primary)' : 'var(--orion-border-strong)' }} />
              <span className="block h-[4px] rounded-full" style={{ width: `${w}%`, background: 'var(--orion-border-strong)', opacity: 0.8 }} />
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
