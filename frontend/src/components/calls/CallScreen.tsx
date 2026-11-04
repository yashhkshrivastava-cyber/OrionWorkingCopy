import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Lock, Maximize2, Mic, MicOff, Minimize2, Phone, PhoneOff, ScreenShare, ScreenShareOff, SignalLow, Video, VideoOff } from 'lucide-react'
import { UserAvatar } from '../UserAvatar'
import { duration, type CallView, type useCallEngine } from './useCallEngine'

type Engine = ReturnType<typeof useCallEngine>

/** Shows a stream in a video element and keeps it shown as tracks join or leave it. */
function Feed({ stream, muted = false, mirror = false, className = '', tracks }: { stream: MediaStream | null; muted?: boolean; mirror?: boolean; className?: string; tracks: number }) {
  const element = useRef<HTMLVideoElement>(null)
  useEffect(() => {
    const el = element.current
    if (!el) return
    if (el.srcObject !== stream) el.srcObject = stream
    if (stream) void el.play().catch(() => null) // a browser may wait for a click to play sound; the call buttons are one
  }, [stream, tracks])
  return <video ref={element} autoPlay playsInline muted={muted} className={`${className} ${mirror ? '-scale-x-100' : ''}`} />
}

/** How loud the other person is right now, 0 to 1, written straight to the element's style so nothing redraws 60 times a second. */
function useLevel(stream: MediaStream | null, target: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!stream || !stream.getAudioTracks().length) return
    let context: AudioContext | null = null
    let frame = 0
    try {
      context = new AudioContext()
      const analyser = context.createAnalyser()
      analyser.fftSize = 256
      context.createMediaStreamSource(stream).connect(analyser)
      const buffer = new Uint8Array(analyser.fftSize)
      let smooth = 0
      const tick = () => {
        analyser.getByteTimeDomainData(buffer)
        let peak = 0
        for (const value of buffer) peak = Math.max(peak, Math.abs(value - 128) / 128)
        smooth = Math.max(peak, smooth * 0.85)
        target.current?.style.setProperty('--level', smooth.toFixed(3))
        frame = requestAnimationFrame(tick)
      }
      tick()
    } catch {
      // no loudness ring in this browser; the call itself is unaffected
    }
    return () => {
      cancelAnimationFrame(frame)
      void context?.close().catch(() => null)
    }
  }, [stream, target])
}

function Elapsed({ since }: { since: number }) {
  const [, tick] = useState(0)
  useEffect(() => {
    const timer = window.setInterval(() => tick((n) => n + 1), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return <span className="tabular-nums">{duration(Date.now() - since)}</span>
}

function status(view: CallView): ReactNode {
  if (view.quality === 'reconnecting' && view.phase === 'active') return 'Reconnecting…'
  switch (view.phase) {
    case 'starting':
      return 'Starting…'
    case 'ringing-out':
      return 'Ringing…'
    case 'connecting':
      return 'Connecting…'
    case 'active':
      return view.connectedAt ? <Elapsed since={view.connectedAt} /> : 'Connected'
    default:
      return ''
  }
}

function Round({ label, onClick, off = false, danger = false, children, hidden = false }: { label: string; onClick: () => void; off?: boolean; danger?: boolean; children: ReactNode; hidden?: boolean }) {
  if (hidden) return null
  const tone = danger ? 'bg-negative text-on-negative hover:opacity-90' : off ? 'bg-white text-black hover:bg-white/90' : 'bg-white/15 text-white hover:bg-white/25'
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label} aria-pressed={danger ? undefined : !off} className={`interactive inline-flex h-14 w-14 items-center justify-center rounded-full backdrop-blur transition-colors ${tone}`}>
      {children}
    </button>
  )
}

/** The call as the person sees it: a card while it rings, a full screen while it runs (or a small pill to get on with other work), and a line when it ends. */
export function CallScreen({ engine }: { engine: Engine }) {
  const { view, accept, hangUp, toggleMic, toggleCamera, toggleScreen } = engine
  const [expanded, setExpanded] = useState(true)
  const ring = useRef<HTMLDivElement>(null)
  const main = view.remoteStreams[0] ?? null
  const screen = view.peerState.screen && view.remoteStreams.length > 1 ? view.remoteStreams[view.remoteStreams.length - 1] : null
  const peerCamOn = view.peerState.cam && Boolean(main && main.getVideoTracks().length)
  useLevel(main, ring)

  // The tab says who is calling while it rings.
  useEffect(() => {
    if (view.phase !== 'ringing-in') return
    const original = document.title
    let flip = false
    const timer = window.setInterval(() => {
      flip = !flip
      document.title = flip ? `${view.peer?.display_name ?? 'Someone'} is calling…` : original
    }, 1100)
    return () => {
      window.clearInterval(timer)
      document.title = original
    }
  }, [view.phase, view.peer?.display_name])

  const name = view.peer?.display_name ?? 'Call'
  const avatar = view.peer ? <UserAvatar user={view.peer} size="lg" /> : null

  // -- ringing for this person -------------------------------------------------------------------------------------

  if (view.phase === 'ringing-in') {
    return (
      <div role="alertdialog" aria-label={`${name} is calling`} className="fixed inset-x-0 top-4 z-[130] mx-auto w-[min(92vw,24rem)] rounded-3xl bg-black/92 p-5 text-white shadow-overlay ring-1 ring-white/10 backdrop-blur-xl pop-in">
        <div className="flex items-center gap-4">
          <span className="relative inline-flex shrink-0">
            <span className="absolute -inset-2 animate-ping rounded-full bg-white/15" aria-hidden="true" />
            <span className="relative">{avatar}</span>
          </span>
          <div className="min-w-0">
            <p className="truncate text-lg font-semibold">{name}</p>
            <p className="flex items-center gap-1.5 text-sm text-white/70">
              {view.kind === 'video' ? <Video className="h-4 w-4" aria-hidden="true" /> : <Phone className="h-4 w-4" aria-hidden="true" />}
              Incoming {view.kind === 'video' ? 'video' : 'voice'} call
            </p>
          </div>
        </div>
        <div className="mt-5 flex items-center justify-center gap-6">
          <button type="button" onClick={hangUp} className="interactive flex flex-col items-center gap-1.5 text-xs text-white/80">
            <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-negative text-on-negative">
              <PhoneOff className="h-6 w-6" aria-hidden="true" />
            </span>
            Decline
          </button>
          {view.kind === 'video' && (
            <button type="button" onClick={() => void accept(false)} className="interactive flex flex-col items-center gap-1.5 text-xs text-white/80">
              <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-white/15">
                <Phone className="h-6 w-6" aria-hidden="true" />
              </span>
              Sound only
            </button>
          )}
          <button type="button" onClick={() => void accept(true)} autoFocus className="interactive flex flex-col items-center gap-1.5 text-xs text-white/80">
            <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-positive text-[color:var(--color-bg)]">
              {view.kind === 'video' ? <Video className="h-6 w-6" aria-hidden="true" /> : <Phone className="h-6 w-6" aria-hidden="true" />}
            </span>
            Answer
          </button>
        </div>
      </div>
    )
  }

  // -- how it ended ---------------------------------------------------------------------------------------------------

  if (view.phase === 'ended') {
    return (
      <div role="status" className="fixed inset-x-0 top-4 z-[130] mx-auto flex w-fit max-w-[92vw] items-center gap-3 rounded-full bg-black/90 px-5 py-3 text-sm text-white shadow-overlay ring-1 ring-white/10 backdrop-blur-xl pop-in">
        <PhoneOff className="h-4 w-4 shrink-0 opacity-80" aria-hidden="true" />
        <span>{view.note}</span>
      </div>
    )
  }

  // -- under way ------------------------------------------------------------------------------------------------------

  const bigIsScreen = Boolean(screen)
  const bar = (
    <div className={`flex items-center justify-center gap-3 ${expanded ? '' : 'gap-1.5'}`}>
      <Round label={view.mic ? 'Mute your microphone' : 'Unmute your microphone'} off={!view.mic} onClick={toggleMic}>
        {view.mic ? <Mic className="h-6 w-6" /> : <MicOff className="h-6 w-6" />}
      </Round>
      <Round label={view.cam ? 'Turn your camera off' : 'Turn your camera on'} off={!view.cam} onClick={() => void toggleCamera()} hidden={view.phase === 'starting'}>
        {view.cam ? <Video className="h-6 w-6" /> : <VideoOff className="h-6 w-6" />}
      </Round>
      <Round
        label={view.sharing ? 'Stop sharing your screen' : 'Share your screen'}
        off={view.sharing}
        onClick={() => void toggleScreen()}
        hidden={view.phase !== 'active' || typeof navigator === 'undefined' || !navigator.mediaDevices?.getDisplayMedia}
      >
        {view.sharing ? <ScreenShareOff className="h-6 w-6" /> : <ScreenShare className="h-6 w-6" />}
      </Round>
      <Round label="End the call" danger onClick={hangUp}>
        <PhoneOff className="h-6 w-6" />
      </Round>
    </div>
  )

  return (
    <div
      role="dialog"
      aria-label={`Call with ${name}`}
      className={
        expanded
          ? 'fixed inset-0 z-[120] flex flex-col bg-black text-white'
          : 'fixed bottom-4 right-4 z-[120] flex w-[min(92vw,22rem)] items-center gap-3 rounded-2xl bg-black/92 p-3 text-white shadow-overlay ring-1 ring-white/10 backdrop-blur-xl'
      }
    >
      {/* The sound of the other person always plays, whether the stage is showing or not. */}
      <Feed stream={main} tracks={view.tracks} className={expanded && peerCamOn && !bigIsScreen ? 'absolute inset-0 h-full w-full bg-black object-contain' : 'pointer-events-none absolute h-px w-px opacity-0'} />

      {expanded ? (
        <>
          <div className="relative z-10 flex items-center justify-between gap-3 bg-gradient-to-b from-black/70 to-transparent px-4 pb-6 pt-4">
            <div className="min-w-0">
              <p className="truncate text-lg font-semibold">{name}</p>
              <p className="flex items-center gap-2 text-sm text-white/75" aria-live="polite">
                <span>{status(view)}</span>
                {view.quality === 'poor' && view.phase === 'active' && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-white/15 px-2 py-0.5 text-xs">
                    <SignalLow className="h-3.5 w-3.5" aria-hidden="true" /> Weak connection
                  </span>
                )}
              </p>
            </div>
            <button type="button" onClick={() => setExpanded(false)} aria-label="Shrink the call and keep working" title="Shrink" className="interactive inline-flex h-10 w-10 items-center justify-center rounded-full bg-white/15 hover:bg-white/25">
              <Minimize2 className="h-5 w-5" />
            </button>
          </div>

          <div className="relative min-h-0 flex-1">
            {bigIsScreen && <Feed stream={screen} muted tracks={view.tracks} className="absolute inset-0 h-full w-full bg-black object-contain" />}
            {!peerCamOn && !bigIsScreen && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-5 px-6 text-center">
                <div ref={ring} className="relative" style={{ ['--level' as string]: 0 }}>
                  <span className="absolute -inset-5 rounded-full bg-white/10" style={{ transform: 'scale(calc(1 + var(--level) * 0.9))', transition: 'transform 90ms linear' }} aria-hidden="true" />
                  <span className="absolute -inset-10 rounded-full bg-white/5" style={{ transform: 'scale(calc(1 + var(--level) * 1.4))', transition: 'transform 120ms linear' }} aria-hidden="true" />
                  <span className="relative block origin-center scale-[1.7]">{avatar}</span>
                </div>
                <p className="mt-10 text-sm text-white/70">
                  {!view.peerState.mic && view.phase === 'active' ? `${name} has muted their microphone` : view.note}
                </p>
              </div>
            )}
            {!view.peerState.mic && view.phase === 'active' && (peerCamOn || bigIsScreen) && (
              <span className="absolute left-4 top-2 inline-flex items-center gap-1.5 rounded-full bg-black/60 px-3 py-1 text-xs">
                <MicOff className="h-3.5 w-3.5" aria-hidden="true" /> {name} is muted
              </span>
            )}
            {view.sharing && (
              <button type="button" onClick={() => void toggleScreen()} className="interactive absolute left-1/2 top-2 -translate-x-1/2 rounded-full bg-primary px-4 py-1.5 text-sm font-semibold text-on-primary shadow-overlay">
                You are sharing your screen · Stop
              </button>
            )}
            {bigIsScreen && peerCamOn && (
              <Feed stream={main} tracks={view.tracks} className="absolute left-4 top-12 aspect-video w-32 rounded-xl bg-black object-cover shadow-overlay ring-1 ring-white/20 sm:w-44" />
            )}
            {view.cam && view.localStream && (
              <Feed stream={view.localStream} muted mirror tracks={view.tracks} className="absolute bottom-4 right-4 aspect-[3/4] w-24 rounded-2xl bg-black object-cover shadow-overlay ring-1 ring-white/25 sm:w-36" />
            )}
          </div>

          {view.note && (peerCamOn || bigIsScreen) && (
            <p role="status" className="absolute inset-x-4 bottom-28 mx-auto w-fit max-w-[90vw] rounded-full bg-black/70 px-4 py-2 text-center text-sm">
              {view.note}
            </p>
          )}

          <div className="relative z-10 bg-gradient-to-t from-black/80 to-transparent px-4 pb-8 pt-8">
            {bar}
            <p className="mt-4 flex items-center justify-center gap-1.5 text-center text-xs text-white/60">
              <Lock className="h-3 w-3" aria-hidden="true" />
              Sound and picture go straight between your devices. Nothing is recorded.
            </p>
          </div>
        </>
      ) : (
        <>
          <button type="button" onClick={() => setExpanded(true)} className="interactive flex min-w-0 flex-1 items-center gap-3 text-left" aria-label="Open the call">
            <UserAvatar user={view.peer ?? { id: 0, display_name: name }} size="md" />
            <span className="min-w-0">
              <span className="block truncate text-sm font-semibold">{name}</span>
              <span className="block text-xs text-white/70">{status(view)}</span>
            </span>
          </button>
          <button type="button" onClick={toggleMic} aria-label={view.mic ? 'Mute your microphone' : 'Unmute your microphone'} className={`interactive inline-flex h-10 w-10 items-center justify-center rounded-full ${view.mic ? 'bg-white/15' : 'bg-white text-black'}`}>
            {view.mic ? <Mic className="h-5 w-5" /> : <MicOff className="h-5 w-5" />}
          </button>
          <button type="button" onClick={() => setExpanded(true)} aria-label="Expand the call" className="interactive inline-flex h-10 w-10 items-center justify-center rounded-full bg-white/15">
            <Maximize2 className="h-5 w-5" />
          </button>
          <button type="button" onClick={hangUp} aria-label="End the call" className="interactive inline-flex h-10 w-10 items-center justify-center rounded-full bg-negative text-on-negative">
            <PhoneOff className="h-5 w-5" />
          </button>
        </>
      )}
    </div>
  )
}
