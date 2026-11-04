import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { MessageCircle, UploadCloud } from 'lucide-react'
import { useAssistant } from '../../ai/AssistantContext'
import { api } from '../../api/client'
import { useAuth } from '../../context/AuthContext'
import { useChat } from '../../context/ChatContext'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'
import { useToast } from '../ui/Toast'
import { UserAvatar } from '../UserAvatar'
import type { ChatMessage, ChatPeer, ChatSettings, ChatThread } from '../../types'
import { Composer, type ComposerHandle } from './Composer'
import { MessageList } from './MessageList'
import { MessageMenu, type MessageMenuTarget } from './MessageMenu'
import { startCall } from '../calls/startCall'
import { ThreadHeader } from './ThreadHeader'
import { ContactPanel, ForwardDialog, InChatSearch, Lightbox, PinnedBar } from './ThreadPanels'
import { useThread } from './useThread'

type Props = {
  /** The conversation, or null for a person you have not written to yet. */
  chatId: number | null
  /** Who a new conversation is with, when there is no chatId yet. */
  newPeer: ChatPeer | null
  chats: ChatThread[]
  people: ChatPeer[]
  draft: string
  onDraftChange: (text: string) => void
  /** Brings a message into view once the conversation has loaded (a search result opened from the list). */
  jump: { messageId: number; nonce: number } | null
  /** The first message of a new conversation: the page makes the conversation, sends it and navigates. */
  onFirstSend: (body: string, file: File | null) => Promise<void>
  onSettingsChanged: (chatId: number, settings: ChatSettings) => void
  onRead: (chatId: number) => void
  onDeleted: (chatId: number) => void
}

/** One open conversation: its header, history, composer and the panels that open from them. */
export function ThreadView({ chatId, newPeer, chats, people, draft, onDraftChange, jump, onFirstSend, onSettingsChanged, onRead, onDeleted }: Props) {
  const { user } = useAuth()
  const { online, isTyping, sendTyping } = useChat()
  const assistant = useAssistant()
  const toast = useToast()
  const navigate = useNavigate()
  const thread = useThread(chatId)
  const composer = useRef<ComposerHandle>(null)
  const frame = useRef<HTMLDivElement>(null)
  const [replyTo, setReplyTo] = useState<ChatMessage | null>(null)
  const [editing, setEditing] = useState<ChatMessage | null>(null)
  const [menu, setMenu] = useState<MessageMenuTarget | null>(null)
  const [forwarding, setForwarding] = useState<ChatMessage | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)
  const [lightbox, setLightbox] = useState<{ url: string; name: string } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [confirmLeave, setConfirmLeave] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [firstBusy, setFirstBusy] = useState(false)
  const [target, setTarget] = useState<{ id: number; nonce: number } | null>(null)
  const dragDepth = useRef(0)
  const meId = user?.id ?? 0

  const summary = thread.summary ?? chats.find((c) => c.id === chatId) ?? null
  const isGroup = summary?.kind === 'group'
  const members = useMemo(() => summary?.members ?? [], [summary?.members])
  const names = useMemo(() => new Map(members.map((m) => [m.id, m.display_name])), [members])
  const peer = summary?.peer ?? newPeer
  const peerOnline = Boolean(peer && (peer.online || online.includes(peer.id)))
  const typingNames = isGroup && chatId ? members.filter((m) => m.id !== meId && isTyping(chatId, m.id)).map((m) => m.display_name.split(' ')[0]) : []
  const typing = isGroup ? typingNames.length > 0 : Boolean(chatId && peer && isTyping(chatId, peer.id))
  const groupHeader =
    isGroup && summary
      ? { title: summary.title ?? 'Group', count: members.length, around: members.filter((m) => m.id !== meId && (m.online || online.includes(m.id))).length, typing: typingNames }
      : undefined
  const settings = thread.summary?.settings ?? summary?.settings ?? null
  const pinnedIds = useMemo(() => new Set(thread.pins.map((p) => p.id)), [thread.pins])

  // A different conversation: nothing carries over.
  useEffect(() => {
    setReplyTo(null)
    setEditing(null)
    setMenu(null)
    setSearchOpen(false)
    setPanelOpen(false)
    setConfirmDelete(false)
    setTarget(null)
  }, [chatId])

  // What the page needs to know once this conversation has been read.
  useEffect(() => {
    if (chatId && thread.summary) onRead(chatId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, thread.summary?.id])

  const goTo = useCallback(
    async (messageId: number) => {
      const found = await thread.jumpTo(messageId)
      if (found) setTarget({ id: messageId, nonce: Date.now() })
      else toast.show('That message is no longer here', { tone: 'info' })
    },
    [thread, toast],
  )

  useEffect(() => {
    if (!jump || !chatId || thread.loading || !thread.summary) return
    void goTo(jump.messageId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jump?.nonce, thread.summary?.id])

  // -- actions ------------------------------------------------------------------------------------------------------

  const send = async ({ body, file }: { body: string; file: File | null }) => {
    if (chatId) {
      thread.send({ body, file, replyTo })
      setReplyTo(null)
      return
    }
    setFirstBusy(true)
    try {
      await onFirstSend(body, file)
    } catch (err) {
      onDraftChange(body)
      toast.show('Could not send the message', { tone: 'error', detail: err instanceof Error ? err.message : undefined })
    } finally {
      setFirstBusy(false)
    }
  }

  const copy = async (message: ChatMessage) => {
    try {
      await navigator.clipboard.writeText(message.body)
      toast.show('Copied to the clipboard')
    } catch {
      toast.show('Could not copy', { tone: 'error', detail: 'Select the text and copy it instead.' })
    }
  }

  const beginReply = (message: ChatMessage) => {
    setEditing(null)
    setReplyTo(message)
    composer.current?.focus()
  }

  const beginEdit = (message: ChatMessage) => {
    setReplyTo(null)
    setEditing(message)
    composer.current?.focus()
  }

  const editLast = () => {
    const last = thread.lastMine
    if (last && last.body && !last.forwarded) beginEdit(last)
  }

  const openMedia = (message: ChatMessage, localUrl?: string) => {
    const url = localUrl || message.media_url
    if (url) setLightbox({ url, name: message.media_name || 'Photo' })
  }

  const forward = async (targetChat: { chat_id?: number; user_id?: number }) => {
    if (!forwarding) return
    try {
      const sent = await api.forwardChatMessage(forwarding.id, targetChat)
      const target = chats.find((c) => c.id === sent.chat_id)
      const who = target?.kind === 'group' ? target.title : target?.peer?.display_name
      toast.show(who ? `Forwarded to ${who}` : 'Message forwarded')
      setForwarding(null)
    } catch (err) {
      toast.show('Could not forward the message', { tone: 'error', detail: err instanceof Error ? err.message : undefined })
    }
  }

  const changeSettings = async (changes: Partial<ChatSettings>) => {
    const next = await thread.updateSettings(changes)
    if (next && chatId) {
      onSettingsChanged(chatId, next)
      if (changes.archived === true) {
        toast.show('Conversation archived')
        navigate('/messages')
      } else if (changes.muted !== undefined) toast.show(changes.muted ? 'Notifications muted' : 'Notifications on')
    }
  }

  const leaveGroup = async () => {
    if (!chatId) return
    setDeleting(true)
    try {
      await api.removeGroupMember(chatId, meId)
      onDeleted(chatId)
    } catch (err) {
      toast.show('Could not leave the group', { tone: 'error', detail: err instanceof Error ? err.message : undefined })
    } finally {
      setDeleting(false)
      setConfirmLeave(false)
    }
  }

  const removeChat = async () => {
    if (!chatId) return
    setDeleting(true)
    try {
      await api.deleteChat(chatId)
      onDeleted(chatId)
    } catch (err) {
      toast.show('Could not delete the conversation', { tone: 'error', detail: err instanceof Error ? err.message : undefined })
    } finally {
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  // -- keyboard and drag-and-drop -----------------------------------------------------------------------------------

  const onKeyDownCapture = (event: React.KeyboardEvent) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f' && chatId) {
      event.preventDefault()
      setSearchOpen(true)
    }
  }

  const hasFiles = (event: React.DragEvent) => [...(event.dataTransfer?.types ?? [])].includes('Files')

  const empty = (
    <div className="flex h-full min-h-[16rem] flex-col items-center justify-center px-6 py-10 text-center">
      {peer ? <UserAvatar user={peer} size="lg" /> : <MessageCircle className="h-10 w-10 text-[color:var(--color-text-faint)]" aria-hidden="true" />}
      <p className="mt-4 text-base font-semibold">{peer ? `Start a conversation with ${peer.display_name}` : 'No messages yet'}</p>
      {peer && <p className="mt-1 max-w-xs text-sm text-[color:var(--color-text-muted)]">Messages and files you send here are private between the two of you.</p>}
      <Button className="mt-4" variant="secondary" onClick={() => void send({ body: '👋', file: null })} disabled={firstBusy}>
        Say hello 👋
      </Button>
    </div>
  )

  return (
    <div
      ref={frame}
      className="relative flex min-h-0 min-w-0 flex-1"
      onKeyDownCapture={onKeyDownCapture}
      onDragEnter={(event) => {
        if (!hasFiles(event)) return
        event.preventDefault()
        dragDepth.current += 1
        setDragging(true)
      }}
      onDragOver={(event) => hasFiles(event) && event.preventDefault()}
      onDragLeave={(event) => {
        if (!hasFiles(event)) return
        dragDepth.current = Math.max(0, dragDepth.current - 1)
        if (dragDepth.current === 0) setDragging(false)
      }}
      onDrop={(event) => {
        if (!hasFiles(event)) return
        event.preventDefault()
        dragDepth.current = 0
        setDragging(false)
        const dropped = event.dataTransfer.files?.[0]
        if (dropped) composer.current?.attach(dropped)
      }}
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <ThreadHeader
          peer={peer}
          online={peerOnline}
          typing={typing}
          fresh={!chatId}
          settings={settings}
          searchOpen={searchOpen}
          panelOpen={panelOpen}
          onToggleSearch={() => setSearchOpen((open) => !open)}
          onTogglePanel={() => setPanelOpen((open) => !open)}
          onSettings={(changes) => void changeSettings(changes)}
          onDelete={() => setConfirmDelete(true)}
          onCall={chatId && !isGroup ? (kind) => startCall(chatId, kind) : undefined}
          group={groupHeader}
        />
        {searchOpen && chatId && (
          <InChatSearch
            chatId={chatId}
            meId={meId}
            peer={peer}
            names={names}
            onGo={(id) => {
              void goTo(id)
            }}
            onClose={() => setSearchOpen(false)}
          />
        )}
        <PinnedBar pins={thread.pins} onGo={(id) => void goTo(id)} onOpenPanel={() => setPanelOpen(true)} />

        {thread.error ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center">
            <p className="text-sm text-negative">{thread.error}</p>
            <Button variant="secondary" onClick={thread.reload}>
              Try again
            </Button>
          </div>
        ) : (
          <MessageList
            key={chatId ?? 'new'}
            messages={thread.messages}
            meId={meId}
            peer={peer}
            peerRead={thread.peerRead}
            readMark={thread.readMark}
            hasMore={thread.hasMore}
            loadingOlder={thread.loadingOlder}
            reachesLatest={thread.reachesLatest}
            loading={thread.loading || (Boolean(chatId) && !thread.summary)}
            pinnedIds={pinnedIds}
            typing={typing}
            group={isGroup}
            names={names}
            typingLabel={typingNames.join(', ')}
            target={target}
            onLoadOlder={() => void thread.loadOlder()}
            onJumpToLatest={thread.jumpToLatest}
            onAtBottom={thread.setAtBottom}
            onMenu={(message, x, y) => setMenu({ message, x, y })}
            onReact={(message, emoji) => void thread.react(message.id, emoji)}
            onReply={beginReply}
            onJump={(id) => void goTo(id)}
            onOpenMedia={openMedia}
            onRetry={thread.retry}
            onDiscard={thread.discard}
            empty={empty}
          />
        )}

        <Composer
          ref={composer}
          chatId={chatId}
          draft={draft}
          onDraftChange={onDraftChange}
          replyTo={replyTo}
          replyName={replyTo ? (replyTo.sender_id === meId ? 'yourself' : names.get(replyTo.sender_id) || peer?.display_name || 'them') : ''}
          onCancelReply={() => setReplyTo(null)}
          editing={editing}
          onCancelEdit={() => setEditing(null)}
          onSaveEdit={async (body) => {
            if (!editing) return
            const done = await thread.edit(editing.id, body)
            if (done) setEditing(null)
          }}
          onSend={send}
          onTyping={() => chatId && sendTyping(chatId)}
          onEditLast={editLast}
          busy={firstBusy}
          aiEnabled={assistant.enabled && !isGroup}
          placeholder={isGroup ? `Message ${summary?.title ?? 'the group'}` : peer ? `Message ${peer.display_name.split(' ')[0]}` : undefined}
        />
      </div>

      {/* The details sit beside the conversation only on a very wide screen; otherwise over it, so messages are never squeezed. */}
      {panelOpen && (
        <div className="absolute inset-y-0 right-0 z-20 flex w-full max-w-[22rem] shadow-overlay max-md:max-w-none 2xl:static 2xl:z-auto 2xl:w-auto 2xl:shadow-none">
          <ContactPanel
            chat={thread.summary}
            peer={peer}
            online={peerOnline}
            pins={thread.pins}
            onClose={() => setPanelOpen(false)}
            onGo={(id) => {
              setPanelOpen(false)
              void goTo(id)
            }}
            onUnpin={(id) => void thread.pin(id, false)}
            onSettings={(changes) => void changeSettings(changes)}
            onDelete={() => setConfirmDelete(true)}
            onOpenMedia={(url, name) => setLightbox({ url, name })}
            onCall={chatId && !isGroup ? (kind) => startCall(chatId, kind) : undefined}
            onSearch={() => {
              setPanelOpen(false)
              setSearchOpen(true)
            }}
            group={isGroup ? { meId, directory: people, online, onLeave: () => setConfirmLeave(true) } : undefined}
          />
        </div>
      )}

      {dragging && (
        <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center bg-[color:var(--color-bg)]/80 backdrop-blur-[2px]">
          <div className="flex flex-col items-center gap-2 rounded-2xl border-2 border-dashed border-[color:var(--color-accent)] bg-surface px-10 py-8 text-center">
            <UploadCloud className="h-8 w-8 text-accent" aria-hidden="true" />
            <p className="text-sm font-semibold">Drop a file to attach it</p>
            <p className="text-xs text-[color:var(--color-text-muted)]">Photos, videos, PDF, Office files, text or zip, up to 12 MB</p>
          </div>
        </div>
      )}

      {menu && (
        <MessageMenu
          target={menu}
          mine={menu.message.sender_id === meId}
          pinned={pinnedIds.has(menu.message.id)}
          onClose={() => setMenu(null)}
          onReact={(emoji) => void thread.react(menu.message.id, emoji)}
          onReply={() => beginReply(menu.message)}
          onCopy={() => void copy(menu.message)}
          onForward={() => setForwarding(menu.message)}
          onPin={() => void thread.pin(menu.message.id, !pinnedIds.has(menu.message.id))}
          onEdit={() => beginEdit(menu.message)}
          onDelete={() => void thread.remove(menu.message.id)}
          onRetry={() => thread.retry(menu.message.id)}
          onDiscard={() => thread.discard(menu.message.id)}
        />
      )}
      {forwarding && <ForwardDialog message={forwarding} chats={chats} people={people} meId={meId} onClose={() => setForwarding(null)} onForward={forward} />}
      {lightbox && <Lightbox url={lightbox.url} name={lightbox.name} onClose={() => setLightbox(null)} />}
      <Modal
        open={confirmDelete}
        onClose={() => !deleting && setConfirmDelete(false)}
        title={isGroup ? 'Delete this group for everyone?' : 'Delete this conversation?'}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(false)} disabled={deleting}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => void removeChat()} loading={deleting}>
              Delete
            </Button>
          </>
        }
      >
        <p className="px-5 py-4 text-sm text-[color:var(--color-text-muted)]">
          {isGroup ? 'Everyone in the group loses it, with its files. This cannot be undone.' : 'It is deleted for both of you, with its files. This cannot be undone.'}
        </p>
      </Modal>
      <Modal
        open={confirmLeave}
        onClose={() => !deleting && setConfirmLeave(false)}
        title="Leave this group?"
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmLeave(false)} disabled={deleting}>
              Stay
            </Button>
            <Button variant="danger" onClick={() => void leaveGroup()} loading={deleting}>
              Leave group
            </Button>
          </>
        }
      >
        <p className="px-5 py-4 text-sm text-[color:var(--color-text-muted)]">
          You will no longer see its messages and an admin has to add you again to bring you back.
          {summary?.my_role === 'admin' && members.filter((m) => m.group_role === 'admin').length === 1 && members.length > 1
            ? ' You are its only admin, so the person who has been in it longest will take over.'
            : ''}
        </p>
      </Modal>
    </div>
  )
}
