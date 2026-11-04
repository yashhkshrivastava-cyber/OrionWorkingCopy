import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, forwardRef, type ClipboardEvent, type KeyboardEvent } from 'react'
import { AlertTriangle, Check, CornerUpLeft, Loader2, Mic, Paperclip, Pencil, SendHorizontal, Smile, Sparkles, X } from 'lucide-react'
import { api } from '../../api/client'
import { EmojiPicker } from '../EmojiPicker'
import type { ChatAssistAction, ChatAssistResult, ChatMessage } from '../../types'
import { fileSize, kindOf, type VoiceFile } from './format'
import { canRecord, RecorderBar } from './RecorderBar'

export const MAX_FILE_BYTES = 12 * 1024 * 1024
const ACCEPT = 'image/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.zip,.ppt,.pptx'
const TONES: { id: string; label: string }[] = [
  { id: 'professional', label: 'More professional' },
  { id: 'friendly', label: 'Friendlier' },
  { id: 'concise', label: 'Shorter' },
  { id: 'casual', label: 'More casual' },
]
const LANGUAGES = ['English', 'Hindi', 'Gujarati', 'Marathi', 'Bengali', 'Tamil', 'Telugu']

export type ComposerHandle = {
  focus: () => void
  /** Puts a file the person dropped or pasted into the composer. */
  attach: (file: File) => void
}

type Props = {
  chatId: number | null
  draft: string
  onDraftChange: (text: string) => void
  replyTo: ChatMessage | null
  replyName: string
  onCancelReply: () => void
  editing: ChatMessage | null
  onCancelEdit: () => void
  onSaveEdit: (body: string) => void | Promise<unknown>
  onSend: (input: { body: string; file: File | null }) => void | Promise<unknown>
  onTyping: () => void
  onEditLast: () => void
  /** While the very first message of a new conversation is being sent. */
  busy?: boolean
  disabled?: boolean
  aiEnabled: boolean
  placeholder?: string
}

function isTouch(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(pointer: coarse)').matches
}

/**
 * The message box. Enter sends and Shift+Enter starts a new line (on a phone Enter starts a new line and the button
 * sends); a draft is kept for each conversation by the page; a file is checked before it is accepted and shown before it is
 * sent; nothing is cleared until the message has been handed over, and a failed send comes back to the thread, not here.
 */
export const Composer = forwardRef<ComposerHandle, Props>(function Composer(
  { chatId, draft, onDraftChange, replyTo, replyName, onCancelReply, editing, onCancelEdit, onSaveEdit, onSend, onTyping, onEditLast, busy = false, disabled = false, aiEnabled, placeholder },
  ref,
) {
  const area = useRef<HTMLTextAreaElement>(null)
  const files = useRef<HTMLInputElement>(null)
  const emojiBox = useRef<HTMLDivElement>(null)
  const aiBox = useRef<HTMLDivElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState('')
  const [emojiOpen, setEmojiOpen] = useState(false)
  const [aiOpen, setAiOpen] = useState(false)
  const [text, setText] = useState(draft)
  const [preview, setPreview] = useState<string | null>(null)
  const [recording, setRecording] = useState(false)
  const sending = useRef(false)

  // The text shown follows the page's draft when the conversation changes or an edit begins.
  useEffect(() => {
    setText(editing ? editing.body : draft)
    setFile(null)
    setFileError('')
    setRecording(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, editing?.id])

  useEffect(() => {
    if (!file || !file.type.startsWith('image/')) {
      setPreview(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  useLayoutEffect(() => {
    const el = area.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 168)}px`
  }, [text])

  useEffect(() => {
    if (!emojiOpen && !aiOpen) return
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node
      if (!emojiBox.current?.contains(target)) setEmojiOpen(false)
      if (!aiBox.current?.contains(target)) setAiOpen(false)
    }
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        setEmojiOpen(false)
        setAiOpen(false)
      }
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [emojiOpen, aiOpen])

  const attach = useCallback((next: File) => {
    if (next.size > MAX_FILE_BYTES) {
      setFileError(`“${next.name}” is ${fileSize(next.size)}. Files can be up to 12 MB.`)
      return
    }
    if (next.size === 0) {
      setFileError(`“${next.name}” is empty.`)
      return
    }
    setFileError('')
    setFile(next)
    area.current?.focus()
  }, [])

  useImperativeHandle(ref, () => ({ focus: () => area.current?.focus(), attach }), [attach])

  const change = (value: string) => {
    setText(value)
    if (!editing) {
      onDraftChange(value)
      if (value.trim()) onTyping()
    }
  }

  const insertAtCursor = (insert: string) => {
    const el = area.current
    const start = el?.selectionStart ?? text.length
    const end = el?.selectionEnd ?? text.length
    const next = `${text.slice(0, start)}${insert}${text.slice(end)}`
    change(next)
    requestAnimationFrame(() => {
      el?.focus()
      el?.setSelectionRange(start + insert.length, start + insert.length)
    })
  }

  const canSend = !disabled && !busy && (editing ? Boolean(text.trim()) : Boolean(text.trim()) || Boolean(file))

  const submit = async () => {
    if (!canSend || sending.current) return
    sending.current = true
    try {
      if (editing) {
        await onSaveEdit(text.trim())
      } else {
        const body = text
        const attached = file
        setText('')
        setFile(null)
        onDraftChange('')
        setEmojiOpen(false)
        await onSend({ body, file: attached })
      }
    } finally {
      sending.current = false
      area.current?.focus()
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Escape') {
      if (editing) onCancelEdit()
      else if (replyTo) onCancelReply()
      return
    }
    if (event.key === 'ArrowUp' && !text && !file && !editing) {
      event.preventDefault()
      onEditLast()
      return
    }
    if (event.key !== 'Enter' || event.nativeEvent.isComposing) return
    const modified = event.metaKey || event.ctrlKey
    if (modified || (!event.shiftKey && !isTouch())) {
      event.preventDefault()
      void submit()
    }
  }

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const item = [...(event.clipboardData?.items ?? [])].find((entry) => entry.kind === 'file')
    const pasted = item?.getAsFile()
    if (pasted) {
      event.preventDefault()
      attach(pasted)
    }
  }

  // ---- the AI helper -------------------------------------------------------------------------------------------

  const [assist, setAssist] = useState<{
    state: 'idle' | 'working' | 'result' | 'consent' | 'unavailable'
    action?: ChatAssistAction
    result?: ChatAssistResult
    request?: { action: ChatAssistAction; tone?: string; language?: string }
  }>({ state: 'idle' })

  const runAssist = async (request: { action: ChatAssistAction; tone?: string; language?: string }, cloudOnce = false) => {
    if (!chatId) return
    setAiOpen(false)
    setAssist({ state: 'working', action: request.action, request })
    try {
      const result = await api.chatAssist(chatId, { ...request, text: text.trim(), allow_cloud_once: cloudOnce })
      if (result.status === 'ok') setAssist({ state: 'result', action: request.action, result, request })
      else if (result.status === 'needs_consent') setAssist({ state: 'consent', action: request.action, result, request })
      else setAssist({ state: 'unavailable', action: request.action, result, request })
    } catch (err) {
      setAssist({ state: 'unavailable', action: request.action, result: { status: 'unavailable', message: err instanceof Error ? err.message : 'AI help is not available.' } })
    }
  }

  const applyText = (value: string) => {
    change(value)
    setAssist({ state: 'idle' })
    requestAnimationFrame(() => area.current?.focus())
  }

  const hasDraft = Boolean(text.trim())
  const canVoice = !editing && !hasDraft && !file

  const startRecording = () => {
    if (!canRecord()) {
      setFileError('Voice notes need the secure address of Orion (https) and a microphone.')
      return
    }
    setFileError('')
    setEmojiOpen(false)
    setRecording(true)
  }

  const sendVoice = (voice: VoiceFile) => {
    setRecording(false)
    void onSend({ body: '', file: voice })
  }

  return (
    <div className="chat-composer border-t border-[color:var(--color-border)] bg-surface px-3 pb-3 pt-3 sm:px-5">
      {assist.state !== 'idle' && (
        <div className="mb-2 rounded-xl border border-[color:var(--color-border)] bg-muted/60 p-3 text-sm" role="region" aria-label="AI suggestion">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-accent">
              <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
              {assist.action === 'rewrite' ? 'Rewrite' : assist.action === 'reply' ? 'Suggested replies' : assist.action === 'summarize' ? 'Summary' : 'Translation'}
              {assist.result?.where && (
                <span className="font-normal text-[color:var(--color-text-faint)]">
                  · {assist.result.where === 'local' ? 'on this computer' : `by cloud AI (${assist.result.provider ?? 'cloud'})`}
                </span>
              )}
            </p>
            <button type="button" onClick={() => setAssist({ state: 'idle' })} aria-label="Dismiss" className="rounded p-1 text-[color:var(--color-text-faint)] hover:bg-surface">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          {assist.state === 'working' && (
            <p className="flex items-center gap-2 text-[color:var(--color-text-muted)]">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Working on it…
            </p>
          )}
          {assist.state === 'unavailable' && (
            <p className="flex items-start gap-2 text-[color:var(--color-text-muted)]">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
              {assist.result?.message || 'AI help is not available right now.'}
            </p>
          )}
          {assist.state === 'consent' && (
            <div className="space-y-2">
              <p className="text-[color:var(--color-text-muted)]">{assist.result?.message}</p>
              <p className="text-xs text-[color:var(--color-text-faint)]">It is sent only for this one request, and you can edit what comes back before sending anything.</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => assist.request && void runAssist(assist.request, true)}
                  className="interactive rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-on-primary"
                >
                  Send this once
                </button>
                <button type="button" onClick={() => setAssist({ state: 'idle' })} className="interactive rounded-lg border border-[color:var(--color-border-strong)] px-3 py-1.5 text-xs font-medium">
                  Cancel
                </button>
              </div>
            </div>
          )}
          {assist.state === 'result' && assist.result?.options && (
            <ul className="space-y-1.5">
              {assist.result.options.map((option) => (
                <li key={option}>
                  <button
                    type="button"
                    onClick={() => applyText(option)}
                    className="interactive w-full rounded-lg border border-[color:var(--color-border)] bg-surface px-3 py-2 text-left hover:border-[color:var(--color-accent)]"
                  >
                    {option}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {assist.state === 'result' && assist.result?.text && (
            <div className="space-y-2">
              <p className="whitespace-pre-wrap rounded-lg bg-surface px-3 py-2">{assist.result.text}</p>
              <div className="flex flex-wrap gap-2">
                {assist.action !== 'summarize' ? (
                  <button type="button" onClick={() => applyText(assist.result!.text!)} className="interactive inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-on-primary">
                    <Check className="h-3.5 w-3.5" aria-hidden="true" />
                    Use this
                  </button>
                ) : (
                  <button type="button" onClick={() => insertAtCursor(assist.result!.text!)} className="interactive rounded-lg border border-[color:var(--color-border-strong)] px-3 py-1.5 text-xs font-medium">
                    Put in the message box
                  </button>
                )}
                <p className="self-center text-[11px] text-[color:var(--color-text-faint)]">Nothing is sent until you press send.</p>
              </div>
            </div>
          )}
        </div>
      )}

      {editing && (
        <div className="mb-2 flex items-center gap-2 rounded-lg border-l-[3px] border-[color:var(--color-accent)] bg-muted px-3 py-1.5 text-xs">
          <Pencil className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate">
            <span className="font-semibold text-accent">Editing message</span> · Enter to save, Esc to cancel
          </span>
          <button type="button" onClick={onCancelEdit} aria-label="Cancel editing" className="rounded p-1 hover:bg-surface">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      {!editing && replyTo && (
        <div className="mb-2 flex items-center gap-2 rounded-lg border-l-[3px] border-[color:var(--color-accent)] bg-muted px-3 py-1.5 text-xs">
          <CornerUpLeft className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
          <span className="min-w-0 flex-1">
            <span className="block truncate font-semibold text-accent">Replying to {replyName}</span>
            <span className="block truncate text-[color:var(--color-text-muted)]">
              {replyTo.body || (replyTo.media_kind === 'image' ? 'Photo' : replyTo.media_kind === 'video' ? 'Video' : replyTo.media_kind === 'audio' ? 'Voice note' : replyTo.media_name || 'File')}
            </span>
          </span>
          <button type="button" onClick={onCancelReply} aria-label="Cancel reply" className="rounded p-1 hover:bg-surface">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      {file && !editing && (
        <div className="mb-2 flex items-center gap-3 rounded-lg border border-[color:var(--color-border)] bg-muted px-2.5 py-2">
          {preview ? (
            <img src={preview} alt="" className="h-12 w-12 shrink-0 rounded-lg object-cover" />
          ) : (
            <span className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-surface text-[color:var(--color-text-muted)]">
              <Paperclip className="h-5 w-5" aria-hidden="true" />
            </span>
          )}
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{file.name}</span>
            <span className="block text-xs text-[color:var(--color-text-muted)]">
              {kindOf(file) === 'image' ? 'Photo' : kindOf(file) === 'video' ? 'Video' : 'File'} · {fileSize(file.size)}
            </span>
          </span>
          <button type="button" onClick={() => setFile(null)} aria-label="Remove attachment" className="rounded p-1.5 text-[color:var(--color-text-muted)] hover:bg-surface">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
      {fileError && (
        <p className="mb-2 flex items-start gap-1.5 text-xs text-negative" role="alert">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {fileError}
        </p>
      )}

      <div
        className={
          recording
            ? 'flex items-end gap-1.5'
            : 'chat-bar flex items-end gap-0.5 rounded-[1.75rem] border border-[color:var(--color-border)] bg-[color:var(--color-bg)] px-2 py-1.5 transition-colors focus-within:border-accent focus-within:ring-[3px] focus-within:ring-[color:var(--orion-ring)]'
        }
      >
        {recording && (
          <RecorderBar
            onDone={sendVoice}
            onCancel={() => setRecording(false)}
            onError={(message) => {
              setRecording(false)
              setFileError(message)
            }}
          />
        )}
        <input
          ref={files}
          type="file"
          className="hidden"
          accept={ACCEPT}
          onChange={(event) => {
            const picked = event.target.files?.[0]
            if (picked) attach(picked)
            event.target.value = ''
          }}
        />
        {!recording && !editing && (
          <button
            type="button"
            onClick={() => files.current?.click()}
            disabled={disabled}
            aria-label="Attach a file"
            title="Attach a file"
            className="interactive mb-0.5 rounded-full p-2.5 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)] disabled:opacity-40"
          >
            <Paperclip className="h-5 w-5" />
          </button>
        )}
        {!recording && <div ref={emojiBox} className="relative">
          {emojiOpen && <EmojiPicker onPick={(emoji) => insertAtCursor(emoji)} />}
          <button
            type="button"
            onClick={() => {
              setEmojiOpen((open) => !open)
              setAiOpen(false)
            }}
            disabled={disabled}
            aria-label="Add an emoji"
            aria-expanded={emojiOpen}
            title="Emoji"
            className={`interactive mb-0.5 rounded-full p-2.5 hover:bg-muted disabled:opacity-40 ${emojiOpen ? 'text-accent' : 'text-[color:var(--color-text-muted)]'}`}
          >
            <Smile className="h-5 w-5" />
          </button>
        </div>}
        {!recording && aiEnabled && chatId && !editing && (
          <div ref={aiBox} className="relative">
            <button
              type="button"
              onClick={() => {
                setAiOpen((open) => !open)
                setEmojiOpen(false)
              }}
              disabled={disabled}
              aria-label="AI help"
              aria-haspopup="menu"
              aria-expanded={aiOpen}
              title="AI help: rewrite, suggest replies, summarise, translate"
              className={`interactive mb-0.5 rounded-full p-2.5 hover:bg-muted disabled:opacity-40 ${aiOpen ? 'text-accent' : 'text-[color:var(--color-text-muted)]'}`}
            >
              <Sparkles className="h-5 w-5" />
            </button>
            {aiOpen && (
              <div role="menu" className="overlay pop-in absolute bottom-full left-0 z-30 mb-2 w-64 rounded-xl border border-[color:var(--color-border)] p-1.5 shadow-overlay">
                <p className="eyebrow px-2.5 pb-1 pt-1.5">Your draft</p>
                {TONES.map((tone) => (
                  <button
                    key={tone.id}
                    type="button"
                    role="menuitem"
                    disabled={!hasDraft}
                    onClick={() => void runAssist({ action: 'rewrite', tone: tone.id })}
                    className="interactive block w-full rounded-lg px-2.5 py-2 text-left text-sm hover:bg-muted disabled:opacity-40"
                  >
                    Rewrite: {tone.label.toLowerCase()}
                  </button>
                ))}
                <p className="eyebrow px-2.5 pb-1 pt-2">Translate your draft to</p>
                <div className="flex flex-wrap gap-1 px-1.5 pb-1">
                  {LANGUAGES.map((language) => (
                    <button
                      key={language}
                      type="button"
                      role="menuitem"
                      disabled={!hasDraft}
                      onClick={() => void runAssist({ action: 'translate', language })}
                      className="interactive rounded-full border border-[color:var(--color-border)] px-2.5 py-1 text-xs hover:bg-muted disabled:opacity-40"
                    >
                      {language}
                    </button>
                  ))}
                </div>
                <p className="eyebrow px-2.5 pb-1 pt-2">This conversation</p>
                <button type="button" role="menuitem" onClick={() => void runAssist({ action: 'reply' })} className="interactive block w-full rounded-lg px-2.5 py-2 text-left text-sm hover:bg-muted">
                  Suggest replies
                </button>
                <button type="button" role="menuitem" onClick={() => void runAssist({ action: 'summarize' })} className="interactive block w-full rounded-lg px-2.5 py-2 text-left text-sm hover:bg-muted">
                  Summarise it
                </button>
              </div>
            )}
          </div>
        )}
        {!recording && <textarea
          ref={area}
          value={text}
          rows={1}
          disabled={disabled}
          onChange={(event) => change(event.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          maxLength={4000}
          placeholder={placeholder || 'Write a message'}
          aria-label="Message"
          enterKeyHint="send"
          className="min-h-[2.75rem] flex-1 resize-none self-center bg-transparent px-2 py-2.5 text-[15px] leading-snug outline-none placeholder:text-[color:var(--color-text-faint)] disabled:opacity-60"
        />}
        {!recording && (canVoice && !busy ? (
          <button
            type="button"
            onClick={startRecording}
            disabled={disabled}
            aria-label="Record a voice note"
            title="Record a voice note"
            className="chat-send interactive mb-0.5 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary text-on-primary transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Mic className="h-5 w-5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => void submit()}
            disabled={!canSend}
            aria-label={editing ? 'Save the edited message' : 'Send message'}
            title={editing ? 'Save (Enter)' : 'Send (Enter)'}
            className="chat-send interactive mb-0.5 inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary text-on-primary transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : editing ? <Check className="h-5 w-5" /> : <SendHorizontal className="h-5 w-5" />}
          </button>
        ))}
      </div>
      {text.length > 3400 && (
        <p className={`mt-1 text-right text-[11px] ${text.length >= 4000 ? 'text-negative' : 'text-[color:var(--color-text-faint)]'}`}>
          {text.length} / 4000
        </p>
      )}
    </div>
  )
})
