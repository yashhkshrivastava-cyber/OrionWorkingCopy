/**
 * The shapes the theme system is made of.
 *
 *   Theme  = identity: palette seeds, accent, typography, default style, motion character
 *   Style  = how surfaces are treated: radius, glass, shadows, glow, gradients, ambient light
 *   Prefs  = what a person chose on top: mode, accent, style, radius, density, scale, contrast, motion
 *
 * A theme is data. `engine.ts` turns (theme, style, prefs, mode) into one flat map of CSS variables, and the whole
 * interface reads those variables, so adding a theme means adding one object to `themes.ts`.
 */

export type Mode = 'light' | 'dark'
export type ModePreference = Mode | 'system'
export type Density = 'compact' | 'comfortable' | 'spacious'
export type Contrast = 'standard' | 'high'
/** Which whole interface is drawn: the original (`classic`, a dark rail and tables of data) or the new one (`lumen`, a floating dock, soft cards and a Today page). */
export type Experience = 'classic' | 'lumen'
export type MotionPreference = 'full' | 'reduced'

/** A few colours that describe a mode of a theme. The engine works out everything else from them. */
export interface PaletteSeed {
  bg: string
  surface: string
  text: string
  /** Navigation rail background. Dark for most themes, even in light mode, so it frames the workspace. */
  rail: string
  /** How strongly borders show, 1 being the standard. Obsidian uses less, Bold more. */
  borderWeight?: number
  /** Overrides for the few colours that must be exactly right for one theme. */
  muted?: string
  textMuted?: string
  textFaint?: string
  border?: string
  borderStrong?: string
}

/** Every colour of one mode of a theme, ready to become CSS variables. */
export interface Palette {
  bg: string
  bgElevated: string
  surface: string
  surfaceHover: string
  muted: string
  border: string
  borderStrong: string
  text: string
  textMuted: string
  textFaint: string
  rail: string
  railRaised: string
  railBorder: string
  railText: string
  railTextFaint: string
  /** Text that must stand out on the rail (the brand name, the active item). */
  railStrong: string
  railHover: string
  railActive: string
  chartTick: string
  chartGrid: string
  chartCursor: string
  /** Status colours. Text on the plain surface, and the soft background that goes with each. */
  positive: string
  positiveDim: string
  negative: string
  negativeDim: string
  warning: string
  warningDim: string
  amber: string
  rose: string
  emerald: string
}

/** Everything that follows from the accent colour. */
export interface AccentTokens {
  /** The brand ramp, 50 to 950. */
  ramp: Record<number, string>
  /** The secondary ramp (the Tally side). */
  secondaryRamp: Record<number, string>
  /** Fill of primary buttons and selected controls, and the text that sits on it. */
  primary: string
  primaryHover: string
  onPrimary: string
  /** The accent as text or an icon on the plain surface, and as a soft background. */
  accent: string
  accentDim: string
  secondary: string
  secondaryDim: string
  /** A gradient from the accent to the second accent, for primary actions and highlights when gradients are on. */
  gradientFrom: string
  gradientTo: string
}

export type StyleId = 'professional' | 'minimal' | 'soft' | 'glass' | 'bold' | 'cinematic' | 'lumen'
export type ShadowLevel = 'none' | 'standard' | 'soft' | 'hard' | 'dramatic'

export interface StyleDef {
  id: StyleId
  name: string
  description: string
  /** Corner radius on the 0 (sharp) to 1 (very round) scale. 0.5 is the standard look. */
  radius: number
  /** How opaque cards and panels are (1 solid, lower shows what is behind) and how much that is blurred. */
  surfaceAlpha: Record<Mode, number>
  blur: number
  shadow: ShadowLevel
  /** 0 to 1: how much the accent glows on primary actions and the active item. */
  glow: number
  /** Whether primary actions and highlights use the theme's accent gradient. */
  gradient: boolean
  /** Whether a soft wash of the accent colours sits behind the workspace. */
  ambient: boolean
  /** How strong that wash is: 1 is the standard. Glass needs more, since it shows through the surfaces. */
  ambientStrength: number
  /** Multiplies border strength: below 1 is softer, above 1 more defined. */
  borderWeight: number
}

export type MotionCharacter = 'crisp' | 'smooth'

export interface ThemeFonts {
  sans: string
  display: string
  /** Google Fonts stylesheet for what the theme needs beyond the default fonts. Loaded only when the theme is used. */
  link?: string
  displayWeight: number
  displayTracking: string
}

export interface ThemeDef {
  id: string
  /** The interface this theme belongs to. Left out, it is a classic theme. */
  experience?: Experience
  name: string
  tagline: string
  description: string
  /** Which mode to switch to when someone picks this theme, so it opens the way it was designed. */
  preferredMode: Mode | null
  style: StyleId
  /** Overrides the style's corner radius for this theme (0 to 1). */
  radius?: number
  accent: Record<Mode, string>
  /** The second accent: the end of the gradient and the colour of the ambient glow. */
  accent2: Record<Mode, string>
  /** The secondary hue used for the Tally side of the business and secondary emphasis. */
  secondary: Record<Mode, string>
  palette: Record<Mode, PaletteSeed>
  fonts: ThemeFonts
  motion: MotionCharacter
  /**
   * Values written exactly as given instead of worked out. The Default theme uses this so it stays identical to the
   * interface before themes existed. An accent the person picks replaces `accent`, never `palette`.
   */
  exact?: { palette?: Record<Mode, Palette>; accent?: Record<Mode, AccentTokens> }
}

/** What a person chose. Anything null follows the theme. This is what is saved. */
export interface AppearancePrefs {
  v: 1
  theme: string
  mode: ModePreference
  accent: string | null
  style: StyleId | null
  radius: number | null
  density: Density
  /** Interface size in percent, 85 to 125. */
  scale: number
  contrast: Contrast
  motion: MotionPreference
  gradient: boolean | null
  ambient: boolean | null
  experience: Experience
}

/** The CSS variables for one resolved appearance, plus what the page needs to know about it. */
export interface ResolvedAppearance {
  mode: Mode
  vars: Record<string, string>
  themeColor: string
  fontLink: string | null
}
