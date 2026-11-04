import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowLeft, History, Maximize2, Minimize2, RotateCcw, SquarePen, TriangleAlert, X } from 'lucide-react'
import { useAssistant } from '../../ai/AssistantContext'
import { AssistantMark, AssistantMessage, UserBubble } from './MessageView'
import { Composer } from './Composer'
import { HistoryList } from './HistoryList'
import { Welcome } from './Welcome'

/**
 * The Copilot's panel. On a wide screen it sits beside the page (so you can keep looking at what you are asking about);
 * on a phone it covers the page. Everything it shows comes from the assistant context.
 */
export function AssistantPanel() {
  const a = useAssistant()
  const scroller = useRef<HTMLDivElement>(null)
  const content = useRef<HTMLDivElement>(null)
  // Whether the view follows the newest words. It is the person's to take away: scrolling up to read stops it, and nothing the
  // panel does afterwards (more words arriving, a chart drawing, an unrelated update) moves them. Reaching the bottom, or asking
  // something, turns it back on.
  const following = useRef(true)
  const lastTop = useRef(0)
  const [away, setAway] = useState(false)
  const empty = a.messages.length === 0

  const jump = () => {
    const node = scroller.current
    if (!node) return
    node.scrollTop = node.scrollHeight
    lastTop.current = node.scrollTop
  }

  const onScroll = () => {
    const node = scroller.current
    if (!node) return
    const top = node.scrollTop
    const gap = node.scrollHeight - top - node.clientHeight
    if (top < lastTop.current - 2 && gap > 4) following.current = false
    else if (gap < 24) following.current = true
    lastTop.current = top
    setAway(gap > 240)
  }

  // A wheel turned upwards is a clear sign that the person wants to read what is above, before the scroll even happens.
  const onWheel = (event: React.WheelEvent) => {
    if (event.deltaY < 0) following.current = false
  }

  // New content: start at the top for a fresh panel, otherwise follow the answer while it is being followed.
  useLayoutEffect(() => {
    const node = scroller.current
    if (!node) return
    if (a.messages.length === 0) {
      node.scrollTop = 0
      lastTop.current = 0
    } else if (following.current) jump()
  }, [a.messages, a.screen, a.loadingConversation])

  // Things that grow after they are drawn (a chart, a table) keep the newest end in view too, but only while following.
  useEffect(() => {
    const node = content.current
    if (!node || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      if (following.current) jump()
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [empty, a.screen, a.open, a.loadingConversation])

  useEffect(() => {
    following.current = true
  }, [a.activeId])

  // Asking something always brings you to the answer, even if you had scrolled up to read.
  const count = a.messages.length
  useLayoutEffect(() => {
    if (count > 0 && a.messages[count - 1].role === 'assistant' && a.streaming) {
      following.current = true
      jump()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count])

  useEffect(() => {
    if (!a.open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !a.streaming && window.matchMedia('(max-width: 1023px)').matches) a.setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [a])

  if (!a.open) return null

  const available = Boolean(a.status?.available)
  const history = a.screen === 'history'
  const lastAssistant = [...a.messages].reverse().find((m) => m.role === 'assistant')

  return (
    <aside
      aria-label="Copilot"
      className={`drawer-right-in fixed inset-0 z-[75] flex min-h-0 flex-col overscroll-contain bg-surface lg:static lg:z-30 lg:shrink-0 lg:border-l lg:border-[color:var(--color-border)] lg:[animation:none] ${
        a.wide ? 'lg:w-[40rem]' : 'lg:w-[26rem]'
      }`}
    >
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-[color:var(--color-border)] px-3 pt-[env(safe-area-inset-top)] sm:px-4">
        {history ? (
          <button type="button" onClick={() => a.setScreen('chat')} aria-label="Back to the conversation" className="interactive -ml-1 rounded-lg p-1.5 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]">
            <ArrowLeft className="h-[18px] w-[18px]" />
          </button>
        ) : (
          <AssistantMark size={26} />
        )}
        <div className="min-w-0 flex-1">
          <p className="t-h3 truncate leading-tight">{history ? 'Conversations' : a.title || 'Copilot'}</p>
          {!history && !a.title && <p className="t-caption hidden leading-tight lg:block">Ctrl+J to open or close</p>}
        </div>
        <button type="button" onClick={a.newChat} title="New conversation" aria-label="New conversation" className="interactive rounded-lg p-1.5 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]">
          <SquarePen className="h-[18px] w-[18px]" />
        </button>
        <button
          type="button"
          onClick={() => a.setScreen(history ? 'chat' : 'history')}
          title="Conversations"
          aria-label="Conversations"
          aria-pressed={history}
          className={`interactive rounded-lg p-1.5 hover:bg-muted ${history ? 'bg-accent-dim text-accent' : 'text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]'}`}
        >
          <History className="h-[18px] w-[18px]" />
        </button>
        <button
          type="button"
          onClick={() => a.setWide(!a.wide)}
          title={a.wide ? 'Make narrower' : 'Make wider'}
          aria-label={a.wide ? 'Make narrower' : 'Make wider'}
          className="interactive hidden rounded-lg p-1.5 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)] lg:block"
        >
          {a.wide ? <Minimize2 className="h-[18px] w-[18px]" /> : <Maximize2 className="h-[18px] w-[18px]" />}
        </button>
        <button type="button" onClick={() => a.setOpen(false)} title="Close" aria-label="Close the Copilot" className="interactive rounded-lg p-1.5 text-[color:var(--color-text-muted)] hover:bg-muted hover:text-[color:var(--color-text)]">
          <X className="h-[18px] w-[18px]" />
        </button>
      </header>

      {history ? (
        <HistoryList />
      ) : (
        <>
          <div className="relative min-h-0 flex-1">
            <div ref={scroller} onScroll={onScroll} onWheel={onWheel} className="h-full overflow-y-auto overscroll-contain" aria-live="polite" aria-busy={a.streaming}>
              {a.loadingConversation ? (
                <p className="p-6 text-center text-sm text-[color:var(--color-text-muted)]">Opening…</p>
              ) : empty ? (
                <Welcome />
              ) : (
                <div ref={content} className="space-y-5 px-3.5 py-4 sm:px-4">
                  {a.messages.map((message, at) =>
                    message.role === 'user' ? (
                      <UserBubble key={message.id} message={message} />
                    ) : (
                      <AssistantMessage
                        key={message.id}
                        message={message}
                        live={a.streaming && at === a.messages.length - 1}
                        last={message === lastAssistant}
                        canRegenerate={!a.streaming && !a.failure}
                        onRegenerate={a.regenerate}
                        onConfirm={(id) => void a.confirmAction(id)}
                        onCancel={(id) => void a.cancelAction(id)}
                        onUseCloud={a.askWithCloud}
                        cloudProvider={a.status?.routing.cloud.provider ?? ''}
                      />
                    ),
                  )}
                  {a.failure && (
                    <div role="alert" className="flex items-start gap-2.5 rounded-xl bg-negative-dim px-3.5 py-3 text-sm text-negative">
                      <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                      <div className="min-w-0 flex-1">
                        <p className="font-medium">{a.failure.message}</p>
                        <div className="mt-2 flex gap-2">
                          {a.failure.retryable && (
                            <button type="button" onClick={a.retry} className="interactive inline-flex items-center gap-1.5 rounded-lg bg-surface px-2.5 py-1 text-xs font-semibold text-[color:var(--color-text)] hover:bg-muted">
                              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                              Try again
                            </button>
                          )}
                          <button type="button" onClick={a.dismissFailure} className="interactive rounded-lg px-2.5 py-1 text-xs font-semibold hover:bg-surface/60">
                            Dismiss
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
            {away && !empty && (
              <button
                type="button"
                onClick={() => {
                  following.current = true
                  jump()
                }}
                className="overlay interactive absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-[color:var(--color-border)] px-3 py-1.5 text-xs font-semibold"
              >
                <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
                Latest
              </button>
            )}
          </div>
          <Composer
            streaming={a.streaming}
            disabled={!available}
            context={a.pageContext}
            share={a.shareContext}
            onShare={a.setShareContext}
            onSend={a.send}
            onStop={a.stop}
            focusKey={`${a.open}-${a.activeId}-${a.screen}`}
            footnote={
              a.status?.routing.cloud.usable_by_you
                ? 'Cloud AI may help with hard questions, with names replaced. Check important figures.'
                : 'Answers come from your data, on this computer. Check important figures.'
            }
          />
        </>
      )}
    </aside>
  )
}
