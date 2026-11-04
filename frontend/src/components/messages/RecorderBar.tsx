import { useEffect, useRef, useState } from 'react'
import { SendHorizontal, Trash2 } from 'lucide-react'
import { playTime, type VoiceFile } from './format'

const MAX_MS = 10 * 60 * 1000
const BARS = 48
const TYPES: { mime: string; ext: string }[] = [
  { mime: 'audio/webm;codecs=opus', ext: 'webm' },
  { mime: 'audio/webm', ext: 'webm' },
  { mime: 'audio/mp4', ext: 'm4a' },
  { mime: 'audio/ogg;codecs=opus', ext: 'ogg' },
]

/** Whether this browser can record a voice note here (it needs the microphone, which browsers give only to a secure address). */
export function canRecord(): boolean {
  return typeof MediaRecorder !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia)
}

/** The loudness picture of a recording: `BARS` numbers from 0 to 100, the loudest bar being 100. */
function shape(levels: number[]): number[] {
  if (!levels.length) return Array.from({ length: BARS }, () => 20)
  const out = Array.from({ length: BARS }, (_, bar) => {
    const from = Math.floor((bar * levels.length) / BARS)
    const to = Math.max(from + 1, Math.floor(((bar + 1) * levels.length) / BARS))
    return Math.max(...levels.slice(from, to))
  })
  const top = Math.max(...out, 0.05)
  return out.map((value) => Math.round(Math.max(8, (value / top) * 100)))
}

/**
 * Takes the place of the message box while a voice note is being recorded: a red dot, how long it has been, the loudness as it
 * happens, a bin to throw it away and a send button. Nothing leaves the browser until send is pressed, and the microphone is
 * released when this goes away, whichever way it ends.
 */
export function RecorderBar({ onDone, onCancel, onError }: { onDone: (file: VoiceFile) => void; onCancel: () => void; onError: (message: string) => void }) {
  const [ms, setMs] = useState(0)
  const [live, setLive] = useState<number[]>(() => Array.from({ length: 28 }, () => 0.05))
  const control = useRef<{ finish: (send: boolean) => void } | null>(null)
  // The latest callbacks, so the recording below is set up once and never restarts when the page redraws.
  const callbacks = useRef({ onDone, onCancel, onError })
  useEffect(() => {
    callbacks.current = { onDone, onCancel, onError }
  })

  useEffect(() => {
    let stopped = false
    let stream: MediaStream | null = null
    let context: AudioContext | null = null
    let timer = 0
    let recorder: MediaRecorder | null = null
    let intent: 'send' | 'cancel' = 'cancel'
    const chunks: Blob[] = []
    const levels: number[] = []
    const began = Date.now()

    const release = () => {
      window.clearInterval(timer)
      stream?.getTracks().forEach((track) => track.stop())
      void context?.close().catch(() => null)
      stream = null
      context = null
    }

    const start = async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })
      } catch (err) {
        const denied = err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'SecurityError')
        callbacks.current.onError(denied ? 'The microphone is blocked. Allow it for this site in the browser, then try again.' : 'No microphone was found.')
        return
      }
      if (stopped) {
        release()
        return
      }
      const type = TYPES.find((candidate) => MediaRecorder.isTypeSupported(candidate.mime)) ?? TYPES[1]
      recorder = new MediaRecorder(stream, { mimeType: type.mime })
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data)
      }
      recorder.onstop = () => {
        const duration = Date.now() - began
        const shouldSend = intent === 'send' && chunks.length > 0 && duration > 400
        release()
        if (shouldSend) {
          const file = new File(chunks, `voice-note.${type.ext}`, { type: type.mime.split(';')[0] }) as VoiceFile
          file.voice = { durationMs: Math.min(duration, MAX_MS), waveform: shape(levels) }
          callbacks.current.onDone(file)
        } else {
          callbacks.current.onCancel()
        }
      }
      recorder.start(250)

      try {
        context = new AudioContext()
        const analyser = context.createAnalyser()
        analyser.fftSize = 512
        context.createMediaStreamSource(stream).connect(analyser)
        const buffer = new Uint8Array(analyser.fftSize)
        timer = window.setInterval(() => {
          analyser.getByteTimeDomainData(buffer)
          let peak = 0
          for (const value of buffer) peak = Math.max(peak, Math.abs(value - 128) / 128)
          levels.push(peak)
          setLive((current) => [...current.slice(1), peak])
          const elapsed = Date.now() - began
          setMs(elapsed)
          if (elapsed >= MAX_MS) control.current?.finish(true)
        }, 80)
      } catch {
        // No loudness picture, but the recording itself still works.
        timer = window.setInterval(() => setMs(Date.now() - began), 250)
      }
    }

    control.current = {
      finish: (send) => {
        intent = send ? 'send' : 'cancel'
        if (recorder && recorder.state !== 'inactive') recorder.stop()
        else {
          release()
          callbacks.current.onCancel()
        }
      },
    }
    void start()

    return () => {
      stopped = true
      if (recorder && recorder.state !== 'inactive') {
        intent = 'cancel'
        recorder.onstop = null
        recorder.stop()
      }
      release()
    }
  }, [])

  return (
    <div className="flex flex-1 items-center gap-2" role="group" aria-label="Recording a voice note">
      <button
        type="button"
        onClick={() => control.current?.finish(false)}
        aria-label="Throw the recording away"
        title="Throw away"
        className="interactive mb-0.5 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-negative hover:bg-negative-dim"
      >
        <Trash2 className="h-5 w-5" />
      </button>
      <div className="chat-input flex min-h-[2.75rem] min-w-0 flex-1 items-center gap-3 rounded-full border border-[color:var(--color-border)] bg-[color:var(--color-bg)] px-3.5">
        <span className="relative inline-flex h-2.5 w-2.5 shrink-0" aria-hidden="true">
          <span className="absolute inset-0 animate-ping rounded-full bg-negative opacity-60" />
          <span className="relative h-2.5 w-2.5 rounded-full bg-negative" />
        </span>
        <span className="w-12 shrink-0 text-sm font-semibold tabular-nums" aria-live="off">
          {playTime(ms)}
        </span>
        <div className="flex h-7 min-w-0 flex-1 items-center gap-[2px] text-accent" aria-hidden="true">
          {live.map((value, index) => (
            <span key={index} className="w-[3px] flex-1 rounded-full bg-current transition-[height] duration-75" style={{ height: `${Math.max(12, Math.min(100, value * 220))}%` }} />
          ))}
        </div>
      </div>
      <button
        type="button"
        onClick={() => control.current?.finish(true)}
        aria-label="Send the voice note"
        title="Send"
        className="chat-send interactive mb-0.5 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary text-on-primary"
      >
        <SendHorizontal className="h-5 w-5" />
      </button>
    </div>
  )
}
