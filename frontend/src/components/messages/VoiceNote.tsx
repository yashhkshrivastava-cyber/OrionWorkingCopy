import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react'
import { Mic, Pause, Play } from 'lucide-react'
import { playTime } from './format'

/** Only one voice note plays at a time: starting one stops the one before it. */
let playing: HTMLAudioElement | null = null

const RATES = [1, 1.5, 2]
const FLAT = Array.from({ length: 32 }, (_, i) => 28 + ((i * 37) % 24))

/**
 * A voice note: play and pause, a picture of its loudness that fills as it plays (tap it to jump), how long it is, and a speed
 * button (1x, 1.5x, 2x). The length and the picture come with the note, so it is drawn before any sound is fetched.
 */
export function VoiceNote({
  url,
  durationMs,
  waveform,
  mine,
  label,
}: {
  url?: string
  durationMs?: number | null
  waveform?: number[]
  mine: boolean
  label: string
}) {
  const audio = useRef<HTMLAudioElement>(null)
  const [on, setOn] = useState(false)
  const [at, setAt] = useState(0)
  const [rate, setRate] = useState(1)
  const [length, setLength] = useState(durationMs ?? 0)
  const bars = useMemo(() => (waveform && waveform.length ? waveform : FLAT), [waveform])
  const share = length > 0 ? Math.min(1, at / length) : 0

  useEffect(() => {
    const el = audio.current
    return () => {
      el?.pause()
      if (playing === el) playing = null
    }
  }, [])

  const toggle = () => {
    const el = audio.current
    if (!el || !url) return
    if (el.paused) {
      if (playing && playing !== el) playing.pause()
      playing = el
      el.playbackRate = rate
      void el.play().catch(() => setOn(false))
    } else {
      el.pause()
    }
  }

  const seek = (event: PointerEvent<HTMLDivElement>) => {
    const el = audio.current
    if (!el || !url || length <= 0) return
    const box = event.currentTarget.getBoundingClientRect()
    const fraction = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width))
    el.currentTime = (fraction * length) / 1000
    setAt(fraction * length)
  }

  const faster = () => {
    const next = RATES[(RATES.indexOf(rate) + 1) % RATES.length]
    setRate(next)
    if (audio.current) audio.current.playbackRate = next
  }

  const tone = mine ? 'text-on-primary' : 'text-accent'
  return (
    <div className="flex min-w-[13rem] max-w-full items-center gap-2.5 py-0.5" role="group" aria-label={label}>
      <audio
        ref={audio}
        src={url}
        preload="none"
        onPlay={() => setOn(true)}
        onPause={() => setOn(false)}
        onEnded={() => {
          setOn(false)
          setAt(0)
        }}
        onTimeUpdate={(event) => setAt(event.currentTarget.currentTime * 1000)}
        onLoadedMetadata={(event) => {
          const seconds = event.currentTarget.duration
          // A recording made in the browser often says its length is infinite; the length that came with the note is then the truth.
          if (!durationMs && Number.isFinite(seconds)) setLength(seconds * 1000)
        }}
      />
      <button
        type="button"
        onClick={toggle}
        disabled={!url}
        aria-label={on ? 'Pause voice note' : 'Play voice note'}
        className={`interactive inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${mine ? 'bg-on-primary/20 text-on-primary' : 'bg-accent-dim text-accent'} disabled:opacity-50`}
      >
        {on ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4 translate-x-px" />}
      </button>
      <div className="min-w-0 flex-1">
        <div
          role="slider"
          aria-label="Position in the voice note"
          aria-valuemin={0}
          aria-valuemax={Math.round(length / 1000)}
          aria-valuenow={Math.round(at / 1000)}
          tabIndex={url ? 0 : -1}
          onPointerDown={seek}
          className={`flex h-8 cursor-pointer items-center gap-[2px] ${tone}`}
        >
          {bars.map((value, index) => (
            <span
              key={index}
              className="w-[3px] flex-1 rounded-full bg-current transition-opacity duration-150"
              style={{ height: `${Math.max(14, value)}%`, opacity: index / bars.length < share ? 1 : 0.4 }}
            />
          ))}
        </div>
        <p className={`mt-0.5 flex items-center justify-between text-[11px] tabular-nums ${mine ? 'text-on-primary/80' : 'text-[color:var(--color-text-muted)]'}`}>
          <span className="inline-flex items-center gap-1">
            <Mic className="h-3 w-3" aria-hidden="true" />
            {playTime(on || at > 0 ? at : length)}
          </span>
          <button type="button" onClick={faster} aria-label={`Speed ${rate}x. Change speed`} className="interactive rounded-full px-1.5 font-semibold hover:bg-on-primary/10">
            {rate}x
          </button>
        </p>
      </div>
    </div>
  )
}
