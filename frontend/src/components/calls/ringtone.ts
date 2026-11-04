/**
 * The sounds of a call, made with the browser's own audio (no sound files): the ring for the person being called, the softer
 * ring-back the caller hears while it rings, and a short blip when a call connects or ends. Quiet on purpose. A browser may keep
 * them silent until the person has used the page once; the call screen is there regardless.
 */

let context: AudioContext | null = null

function audio(): AudioContext | null {
  try {
    context ??= new AudioContext()
    if (context.state === 'suspended') void context.resume().catch(() => null)
    return context
  } catch {
    return null // no audio in this browser: the call is silent but works
  }
}

function note(c: AudioContext, frequency: number, at: number, length: number, volume: number) {
  const oscillator = c.createOscillator()
  const gain = c.createGain()
  oscillator.type = 'sine'
  oscillator.frequency.value = frequency
  gain.gain.setValueAtTime(0, at)
  gain.gain.linearRampToValueAtTime(volume, at + 0.03)
  gain.gain.exponentialRampToValueAtTime(0.0001, at + length)
  oscillator.connect(gain).connect(c.destination)
  oscillator.start(at)
  oscillator.stop(at + length + 0.05)
}

/** Starts a repeating tone and returns the function that stops it. */
export function startTone(kind: 'ring' | 'ringback'): () => void {
  const c = audio()
  if (!c) return () => undefined
  const play = () => {
    const t = c.currentTime + 0.02
    if (kind === 'ring') {
      // two rising pairs, like a phone
      for (const at of [0, 0.5]) {
        note(c, 659, t + at, 0.32, 0.12)
        note(c, 880, t + at + 0.16, 0.32, 0.12)
      }
    } else {
      note(c, 440, t, 1.1, 0.06)
      note(c, 480, t, 1.1, 0.06)
    }
  }
  play()
  const timer = window.setInterval(play, kind === 'ring' ? 2600 : 3600)
  return () => window.clearInterval(timer)
}

/** One short sound: a rising blip when the call connects, a falling one when it ends. */
export function blip(kind: 'connect' | 'end') {
  const c = audio()
  if (!c) return
  const t = c.currentTime + 0.01
  const [first, second] = kind === 'connect' ? [523, 784] : [660, 440]
  note(c, first, t, 0.14, 0.1)
  note(c, second, t + 0.12, 0.2, 0.1)
}
