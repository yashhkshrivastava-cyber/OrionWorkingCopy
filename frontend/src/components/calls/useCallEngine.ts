import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import { useAuth } from '../../context/AuthContext'
import { useChat, type CallEvent } from '../../context/ChatContext'
import type { CallRing, ChatPeer } from '../../types'
import { blip, startTone } from './ringtone'

export type Phase = 'idle' | 'starting' | 'ringing-out' | 'ringing-in' | 'connecting' | 'active' | 'ended'
export type PeerState = { mic: boolean; cam: boolean; screen: boolean }

export interface CallView {
  phase: Phase
  kind: 'voice' | 'video'
  chatId: number | null
  callId: number | null
  peer: ChatPeer | null
  incoming: boolean
  /** What to say after something went wrong or the call ended. */
  note: string
  connectedAt: number | null
  mic: boolean
  cam: boolean
  sharing: boolean
  peerState: PeerState
  localStream: MediaStream | null
  /** The streams the other person sends: the first is them, any later one is a screen they share. */
  remoteStreams: MediaStream[]
  /** Goes up whenever a track joins a stream already known, so the screen draws it. */
  tracks: number
  quality: 'good' | 'poor' | 'reconnecting'
}

const IDLE: CallView = {
  phase: 'idle',
  kind: 'voice',
  chatId: null,
  callId: null,
  peer: null,
  incoming: false,
  note: '',
  connectedAt: null,
  mic: true,
  cam: false,
  sharing: false,
  peerState: { mic: true, cam: false, screen: false },
  localStream: null,
  remoteStreams: [],
  tracks: 0,
  quality: 'good',
}

const NOTE_SHOWN_MS = 3200
const LOST_AFTER_MS = 20_000

/** 3:07 or 1:02:09 */
export function duration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`
}

function friendly(err: unknown, what: 'microphone' | 'screen'): string {
  const name = err instanceof DOMException ? err.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return what === 'screen' ? 'Screen sharing was not allowed.' : 'The microphone is blocked. Allow it for this site in the browser, then try again.'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'No microphone was found.'
  if (name === 'NotReadableError') return 'The microphone is being used by another program.'
  return err instanceof Error && err.message ? err.message : 'Could not start the call.'
}

type Held = {
  pc: RTCPeerConnection | null
  local: MediaStream | null
  callId: number | null
  polite: boolean
  makingOffer: boolean
  ignoreOffer: boolean
  allowOffers: boolean
  candidates: RTCIceCandidateInit[]
  queue: Promise<void>
  ice: RTCIceServer[]
  videoSender: RTCRtpSender | null
  screenSender: RTCRtpSender | null
  screenTrack: MediaStreamTrack | null
  stopTone: () => void
  timers: { note?: number; stats?: number; lost?: number }
}

const fresh = (): Held => ({
  pc: null,
  local: null,
  callId: null,
  polite: false,
  makingOffer: false,
  ignoreOffer: false,
  allowOffers: false,
  candidates: [],
  queue: Promise.resolve(),
  ice: [],
  videoSender: null,
  screenSender: null,
  screenTrack: null,
  stopTone: () => undefined,
  timers: {},
})

/**
 * Runs one call at a time: ringing, answering, setting up the connection between the two browsers, the microphone, camera and
 * screen, and everything that ends it. The set-up messages travel over the chat's WebSocket (the server only passes them on);
 * the sound and picture go straight between the two browsers. The two sides follow the "perfect negotiation" pattern, so it does
 * not matter if both change something (a camera turned on, a screen shared) at the same moment: the person who answered gives way.
 */
export function useCallEngine() {
  const { user } = useAuth()
  const { subscribe, sendSocket, connected } = useChat()
  const meId = user?.id ?? 0
  const [view, setView] = useState<CallView>(IDLE)
  const viewRef = useRef<CallView>(IDLE)
  const held = useRef<Held>(fresh())

  const patch = useCallback((changes: Partial<CallView>) => {
    viewRef.current = { ...viewRef.current, ...changes }
    setView(viewRef.current)
  }, [])

  const signal = useCallback(
    (data: Record<string, unknown>) => {
      const id = held.current.callId
      if (id !== null) sendSocket({ type: 'call_signal', call_id: id, data })
    },
    [sendSocket],
  )

  const sendState = useCallback(() => {
    const v = viewRef.current
    signal({ type: 'state', mic: v.mic, cam: v.cam, screen: v.sharing })
  }, [signal])

  /** Puts everything away: the connection, the microphone and camera, the sounds. `note` is what the screen says for a moment. */
  const finish = useCallback(
    (note: string, keep?: Partial<CallView>) => {
      const h = held.current
      h.stopTone()
      window.clearInterval(h.timers.stats)
      window.clearTimeout(h.timers.lost)
      window.clearTimeout(h.timers.note)
      h.screenTrack?.stop()
      h.local?.getTracks().forEach((track) => track.stop())
      if (h.pc) {
        h.pc.ontrack = null
        h.pc.onicecandidate = null
        h.pc.onnegotiationneeded = null
        h.pc.onconnectionstatechange = null
        h.pc.close()
      }
      const before = viewRef.current
      held.current = fresh()
      if (!note) {
        viewRef.current = IDLE
        setView(IDLE)
        return
      }
      viewRef.current = { ...IDLE, phase: 'ended', note, kind: before.kind, chatId: before.chatId, peer: before.peer, incoming: before.incoming, ...keep }
      setView(viewRef.current)
      held.current.timers.note = window.setTimeout(() => {
        viewRef.current = IDLE
        setView(IDLE)
      }, NOTE_SHOWN_MS)
    },
    [],
  )

  // -- the microphone and camera ----------------------------------------------------------------------------------

  const acquire = useCallback(async (kind: 'voice' | 'video') => {
    const devices = navigator.mediaDevices
    if (!devices?.getUserMedia) throw new Error('Calls need the secure address of Orion (https).')
    const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    if (kind === 'video') {
      try {
        return { stream: await devices.getUserMedia({ audio, video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } } }), note: '' }
      } catch (err) {
        // A camera that is missing or blocked should not stop a call: fall back to sound only, and say so.
        try {
          return { stream: await devices.getUserMedia({ audio }), note: 'Your camera could not be used, so this call is sound only.' }
        } catch {
          throw new Error(friendly(err, 'microphone'))
        }
      }
    }
    try {
      return { stream: await devices.getUserMedia({ audio }), note: '' }
    } catch (err) {
      throw new Error(friendly(err, 'microphone'))
    }
  }, [])

  // -- the connection -------------------------------------------------------------------------------------------------

  const makeConnection = useCallback(
    (polite: boolean) => {
      const h = held.current
      h.polite = polite
      const pc = new RTCPeerConnection({ iceServers: h.ice })
      h.pc = pc
      pc.onicecandidate = (event) => {
        if (event.candidate) signal({ type: 'candidate', candidate: event.candidate.toJSON() })
      }
      pc.ontrack = (event) => {
        const stream = event.streams[0] ?? new MediaStream([event.track])
        const known = viewRef.current.remoteStreams
        patch({ remoteStreams: known.some((s) => s.id === stream.id) ? known : [...known, stream], tracks: viewRef.current.tracks + 1 })
        event.track.onunmute = () => patch({ tracks: viewRef.current.tracks + 1 })
      }
      pc.onnegotiationneeded = async () => {
        if (!held.current.allowOffers) return
        try {
          h.makingOffer = true
          await pc.setLocalDescription()
          const local = pc.localDescription
          if (local) signal({ type: local.type, sdp: local.sdp })
        } catch {
          // The connection was closed under us (the call ended); nothing to set up any more.
        } finally {
          h.makingOffer = false
        }
      }
      pc.onconnectionstatechange = () => {
        window.clearTimeout(h.timers.lost)
        if (pc.connectionState === 'connected') {
          const first = viewRef.current.connectedAt === null
          patch({ phase: 'active', connectedAt: viewRef.current.connectedAt ?? Date.now(), quality: 'good' })
          if (first) {
            h.stopTone()
            blip('connect')
            sendState()
          }
        } else if (pc.connectionState === 'disconnected' || pc.connectionState === 'failed') {
          patch({ quality: 'reconnecting' })
          if (pc.connectionState === 'failed') pc.restartIce()
          h.timers.lost = window.setTimeout(() => {
            const id = held.current.callId
            if (id !== null) sendSocket({ type: 'call_end', call_id: id })
            finish('The connection was lost.')
          }, LOST_AFTER_MS)
        }
      }
      // How the line is doing, every few seconds: slow or lossy shows a warning on the call screen.
      let lastLost = 0
      let lastReceived = 0
      h.timers.stats = window.setInterval(async () => {
        if (pc.connectionState !== 'connected') return
        try {
          let rtt = 0
          let lost = 0
          let received = 0
          const stats = await pc.getStats()
          stats.forEach((report) => {
            if (report.type === 'candidate-pair' && report.state === 'succeeded' && report.nominated) rtt = report.currentRoundTripTime ?? rtt
            if (report.type === 'inbound-rtp') {
              lost += report.packetsLost ?? 0
              received += report.packetsReceived ?? 0
            }
          })
          const dLost = lost - lastLost
          const dReceived = received - lastReceived
          lastLost = lost
          lastReceived = received
          const loss = dLost + dReceived > 0 ? dLost / (dLost + dReceived) : 0
          patch({ quality: rtt > 0.5 || loss > 0.1 ? 'poor' : 'good' })
        } catch {
          // Statistics are only a courtesy; a failure to read them changes nothing about the call.
        }
      }, 3000)
      return pc
    },
    [signal, sendState, patch, sendSocket, finish],
  )

  const addLocalTracks = useCallback(() => {
    const h = held.current
    if (!h.pc || !h.local) return
    for (const track of h.local.getTracks()) {
      const sender = h.pc.addTrack(track, h.local)
      if (track.kind === 'video') h.videoSender = sender
    }
  }, [])

  const handleSignal = useCallback(
    async (data: Record<string, unknown>) => {
      const h = held.current
      if (data.type === 'state') {
        patch({ peerState: { mic: data.mic !== false, cam: data.cam === true, screen: data.screen === true } })
        return
      }
      const pc = h.pc
      if (!pc) return
      try {
        if (data.type === 'offer' || data.type === 'answer') {
          const type = data.type
          const collision = type === 'offer' && (h.makingOffer || pc.signalingState !== 'stable')
          h.ignoreOffer = !h.polite && collision
          if (h.ignoreOffer) return
          await pc.setRemoteDescription({ type, sdp: String(data.sdp ?? '') })
          h.allowOffers = true
          if (type === 'offer') {
            await pc.setLocalDescription()
            const local = pc.localDescription
            if (local) signal({ type: local.type, sdp: local.sdp })
          }
          for (const pending of h.candidates.splice(0)) await pc.addIceCandidate(pending).catch(() => null) // a late candidate for a replaced offer is harmless
        } else if (data.type === 'candidate' && data.candidate) {
          const candidate = data.candidate as RTCIceCandidateInit
          if (!pc.remoteDescription) h.candidates.push(candidate)
          else await pc.addIceCandidate(candidate).catch((err) => {
            if (!h.ignoreOffer) throw err
          })
        }
      } catch {
        patch({ note: 'Something went wrong setting up the call. If there is no sound, hang up and call again.' })
      }
    },
    [patch, signal],
  )

  // -- what the person does ---------------------------------------------------------------------------------------

  const start = useCallback(
    async (chatId: number, kind: 'voice' | 'video') => {
      const phase = viewRef.current.phase
      if (phase !== 'idle' && phase !== 'ended') return
      window.clearTimeout(held.current.timers.note)
      held.current = fresh()
      viewRef.current = { ...IDLE, phase: 'starting', kind, chatId }
      setView(viewRef.current)
      try {
        held.current.ice = (await api.callConfig()).ice_servers
      } catch {
        held.current.ice = [] // on one network or over Tailscale none are needed
      }
      let got: { stream: MediaStream; note: string }
      try {
        got = await acquire(kind)
      } catch (err) {
        finish(err instanceof Error ? err.message : 'Could not start the call.')
        return
      }
      if (viewRef.current.phase !== 'starting') {
        got.stream.getTracks().forEach((track) => track.stop()) // hung up while the microphone was being asked for
        return
      }
      held.current.local = got.stream
      patch({ localStream: got.stream, cam: got.stream.getVideoTracks().length > 0, note: got.note })
      if (!sendSocket({ type: 'call_invite', chat_id: chatId, kind })) finish('You are offline. Check your connection and try again.')
    },
    [acquire, finish, patch, sendSocket],
  )

  const accept = useCallback(
    async (withVideo = true) => {
      const v = viewRef.current
      if (v.phase !== 'ringing-in' || v.callId === null) return
      held.current.stopTone()
      patch({ phase: 'connecting' })
      try {
        held.current.ice = (await api.callConfig()).ice_servers
      } catch {
        held.current.ice = []
      }
      let got: { stream: MediaStream; note: string }
      try {
        got = await acquire(withVideo ? v.kind : 'voice')
      } catch (err) {
        sendSocket({ type: 'call_end', call_id: v.callId })
        finish(err instanceof Error ? err.message : 'Could not answer the call.')
        return
      }
      if (viewRef.current.phase !== 'connecting') {
        got.stream.getTracks().forEach((track) => track.stop()) // the caller gave up while the microphone was being asked for
        return
      }
      held.current.local = got.stream
      patch({ localStream: got.stream, cam: got.stream.getVideoTracks().length > 0, note: got.note })
      makeConnection(true)
      addLocalTracks()
      sendSocket({ type: 'call_accept', call_id: v.callId })
      sendState()
    },
    [acquire, addLocalTracks, finish, makeConnection, patch, sendSocket, sendState],
  )

  const hangUp = useCallback(() => {
    const v = viewRef.current
    const id = held.current.callId
    if (id !== null) sendSocket({ type: 'call_end', call_id: id })
    finish(v.connectedAt ? `Call ended · ${duration(Date.now() - v.connectedAt)}` : '')
    if (v.connectedAt) blip('end')
  }, [finish, sendSocket])

  const toggleMic = useCallback(() => {
    const h = held.current
    const next = !viewRef.current.mic
    h.local?.getAudioTracks().forEach((track) => (track.enabled = next))
    patch({ mic: next })
    sendState()
  }, [patch, sendState])

  const toggleCamera = useCallback(async () => {
    const h = held.current
    const v = viewRef.current
    if (!h.local) return
    try {
      if (v.cam) {
        for (const track of h.local.getVideoTracks()) {
          track.stop()
          h.local.removeTrack(track)
        }
        if (h.videoSender) await h.videoSender.replaceTrack(null)
        patch({ cam: false, localStream: new MediaStream(h.local.getTracks()) })
      } else {
        const camera = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 } } })
        const track = camera.getVideoTracks()[0]
        h.local.addTrack(track)
        if (h.videoSender) await h.videoSender.replaceTrack(track)
        else if (h.pc) h.videoSender = h.pc.addTrack(track, h.local) // a sound-only call turning its camera on: the connection is set up again
        patch({ cam: true, localStream: new MediaStream(h.local.getTracks()) })
      }
      sendState()
    } catch (err) {
      patch({ note: err instanceof DOMException && err.name === 'NotAllowedError' ? 'The camera is blocked. Allow it for this site in the browser.' : 'The camera could not be started.' })
    }
  }, [patch, sendState])

  const stopSharing = useCallback(() => {
    const h = held.current
    if (h.screenSender && h.pc) {
      try {
        h.pc.removeTrack(h.screenSender)
      } catch {
        // the connection is already closed
      }
    }
    h.screenTrack?.stop()
    h.screenSender = null
    h.screenTrack = null
    patch({ sharing: false })
    sendState()
  }, [patch, sendState])

  const toggleScreen = useCallback(async () => {
    const h = held.current
    if (viewRef.current.sharing) {
      stopSharing()
      return
    }
    if (!h.pc || !navigator.mediaDevices?.getDisplayMedia) return
    try {
      const display = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false })
      const track = display.getVideoTracks()[0]
      h.screenTrack = track
      h.screenSender = h.pc.addTrack(track, display) // its own stream, so the other side can tell a screen from a camera
      track.onended = () => stopSharing() // the browser's own "Stop sharing" button
      patch({ sharing: true })
      sendState()
    } catch (err) {
      // Closing the picker is not an error worth a message.
      if (!(err instanceof DOMException && err.name === 'NotAllowedError')) patch({ note: friendly(err, 'screen') })
    }
  }, [patch, sendState, stopSharing])

  // -- what the server says ---------------------------------------------------------------------------------------

  const presentRing = useCallback(
    (call: CallRing) => {
      held.current = fresh()
      held.current.callId = call.id
      held.current.stopTone = startTone('ring')
      viewRef.current = { ...IDLE, phase: 'ringing-in', incoming: true, kind: call.kind, chatId: call.chat_id, callId: call.id, peer: call.caller }
      setView(viewRef.current)
      try {
        navigator.vibrate?.([300, 200, 300])
      } catch {
        // not every browser can vibrate
      }
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted' && document.hidden) {
        try {
          const shown = new Notification(`${call.caller.display_name} is calling`, { body: call.kind === 'video' ? 'Video call' : 'Voice call', requireInteraction: true, tag: `call-${call.id}` })
          shown.onclick = () => window.focus()
        } catch {
          // a notification that cannot be shown is only a courtesy
        }
      }
    },
    [],
  )

  const onEvent = useRef<(event: CallEvent) => void>(() => undefined)
  useEffect(() => {
    onEvent.current = (event) => {
      const h = held.current
      const v = viewRef.current
      switch (event.type) {
        case 'call_started': {
          if (v.phase !== 'starting') {
            sendSocket({ type: 'call_end', call_id: event.call.id }) // hung up before the call had a number: end it on the server too
            return
          }
          h.callId = event.call.id
          h.stopTone = startTone('ringback')
          patch({ phase: 'ringing-out', callId: event.call.id, peer: event.peer })
          return
        }
        case 'call_ring': {
          if (v.phase !== 'idle' && v.phase !== 'ended') return
          window.clearTimeout(h.timers.note)
          presentRing(event.call)
          return
        }
        case 'call_accepted': {
          if (event.call_id !== h.callId) return
          if (event.by === meId) {
            // Answered here: nothing to do. Answered on another of this person's devices: stop ringing.
            if (v.phase === 'ringing-in') finish('Answered on another device')
            return
          }
          if (v.phase !== 'ringing-out') return
          h.stopTone()
          patch({ phase: 'connecting' })
          makeConnection(false)
          h.allowOffers = true
          addLocalTracks()
          sendState()
          return
        }
        case 'call_signal': {
          if (event.call_id !== h.callId) return
          h.queue = h.queue.then(() => handleSignal(event.data))
          return
        }
        case 'call_ended': {
          const mine = event.call_id === h.callId || (v.phase === 'starting' && event.chat_id === v.chatId)
          if (!mine) return
          const name = event.peer?.display_name || v.peer?.display_name || 'They'
          const wasConnected = v.connectedAt !== null
          let note = ''
          if (wasConnected) note = `Call ended · ${duration(Date.now() - (v.connectedAt ?? Date.now()))}`
          else if (event.outcome === 'missed') {
            note =
              v.incoming
                ? 'Missed call'
                : event.reason === 'offline'
                  ? `${name} is offline. They will see a missed call.`
                  : event.reason === 'busy'
                    ? `${name} is on another call.`
                    : `${name} did not answer.`
          } else if (event.outcome === 'declined') note = v.incoming ? '' : `${name} declined the call.`
          else if (event.outcome === 'cancelled') note = v.incoming ? 'Call cancelled' : ''
          finish(note, { peer: event.peer ?? v.peer })
          if (wasConnected) blip('end')
          return
        }
        case 'call_error': {
          if (v.phase === 'starting') finish(event.message)
          else patch({ note: event.message })
        }
      }
    }
  })

  useEffect(() => subscribe((event) => {
    if (event.type.startsWith('call_')) onEvent.current(event as CallEvent)
  }), [subscribe])

  // A page that has just loaded may have missed the ring, and so may one that lost its connection a moment ago.
  useEffect(() => {
    if (!connected || !meId) return
    let cancelled = false
    api
      .callRinging()
      .then(({ call }) => {
        if (cancelled || !call) return
        const phase = viewRef.current.phase
        if (phase === 'idle' || phase === 'ended') presentRing(call)
      })
      .catch(() => null) // the next ring will arrive over the socket anyway
    return () => {
      cancelled = true
    }
  }, [connected, meId, presentRing])

  // A call cannot survive its page closing: tell the server so the other side is not left ringing.
  useEffect(() => {
    const leave = () => {
      const id = held.current.callId
      if (id !== null && viewRef.current.phase !== 'idle') sendSocket({ type: 'call_end', call_id: id })
    }
    window.addEventListener('pagehide', leave)
    return () => window.removeEventListener('pagehide', leave)
  }, [sendSocket])

  // Anything on a page can ask to start a call.
  useEffect(() => {
    const onStart = (event: Event) => {
      const detail = (event as CustomEvent<{ chatId: number; kind: 'voice' | 'video' }>).detail
      if (detail && Number.isFinite(detail.chatId)) void start(detail.chatId, detail.kind)
    }
    window.addEventListener('orion-call-start', onStart)
    return () => window.removeEventListener('orion-call-start', onStart)
  }, [start])

  // Everything is put away when the host goes (signing out).
  useEffect(
    () => () => {
      const h = held.current
      h.stopTone()
      h.local?.getTracks().forEach((track) => track.stop())
      h.pc?.close()
    },
    [],
  )

  return { view, accept, decline: hangUp, hangUp, toggleMic, toggleCamera, toggleScreen }
}
