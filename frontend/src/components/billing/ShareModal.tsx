import { useEffect, useState } from 'react'
import { Download, Mail, MessageCircle } from 'lucide-react'
import { api } from '../../api/client'
import { AiButton, AiNotice, AiProvenance, useAiTask } from '../ai/AiTask'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Field, Input, Select, Textarea } from '../ui/Field'
import { Modal } from '../ui/Modal'
import { Tabs } from '../ui/Tabs'
import { formatDay } from './BillDocument'
import type { ShareDefaults } from '../../types'

type Channel = 'email' | 'whatsapp'

const REMINDER_TONES = [
  { id: 'polite', label: 'Polite' },
  { id: 'friendly', label: 'Friendly' },
  { id: 'firm', label: 'Firm' },
  { id: 'final', label: 'Final notice' },
]

/**
 * Sends a bill, or a reminder with a statement of unpaid bills, by email or WhatsApp.
 *
 * `target` is the API path under /billing (`bills/<id>` or `receivables/<client>`). Email goes
 * out from the server with the PDF attached. WhatsApp cannot take an attachment from a link, so
 * it opens WhatsApp with the message ready and the PDF can be downloaded here to attach by hand.
 */
export function ShareModal({
  open,
  title,
  target,
  pdfPath,
  pdfName,
  letterhead = false,
  onClose,
  onSent,
}: {
  open: boolean
  title: string
  target: string
  pdfPath: string
  pdfName: string
  /** Draw the PDF, attached or downloaded, on the company letterhead. */
  letterhead?: boolean
  onClose: () => void
  onSent?: () => void
}) {
  const [defaults, setDefaults] = useState<ShareDefaults | null>(null)
  const [channel, setChannel] = useState<Channel>('email')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState<{ text: string; link?: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [tone, setTone] = useState('polite')
  const reword = useAiTask<{ message: string }>()
  // Only a reminder for a client can be reworded: the statement in it is filled in by the server, not the AI.
  const clientCode = target.startsWith('receivables/') ? decodeURIComponent(target.slice('receivables/'.length)) : ''

  const load = () =>
    api
      .shareDefaults(target)
      .then((d) => {
        setDefaults(d)
        return d
      })
      .catch((e: Error) => {
        setError(e.message)
        return null
      })

  useEffect(() => {
    if (!open) return
    setDefaults(null)
    setError('')
    setDone(null)
    setChannel('email')
    reword.reset()
    load().then((d) => {
      if (!d) return
      setEmail(d.email ?? '')
      setPhone(d.phone ?? '')
      setMessage(d.message)
      if (!d.email_enabled) setChannel('whatsapp')
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, target])

  const send = async () => {
    setBusy(true)
    setError('')
    setDone(null)
    try {
      if (channel === 'email') {
        const sent = await api.shareByEmail(target, email, message, letterhead)
        setDone({ text: `Sent to ${sent.to}, with the PDF attached.` })
      } else {
        const { url } = await api.shareByWhatsApp(target, phone, message)
        window.open(url, '_blank', 'noopener')
        setDone({ text: 'WhatsApp is opening with the message ready. Download the PDF here to attach it.', link: url })
      }
      onSent?.()
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const download = async () => {
    setError('')
    try {
      await api.downloadPdf(letterhead ? `${pdfPath}?letterhead=true` : pdfPath, pdfName)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const ready = Boolean(defaults) && message.trim() !== '' && (channel === 'email' ? email.trim() !== '' : phone.trim() !== '')

  return (
    <Modal
      open={open}
      title={title}
      size="xl"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={download}>
            <Download className="h-4 w-4" /> Download PDF
          </Button>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button
            onClick={send}
            loading={busy}
            disabled={!ready || (channel === 'email' && !defaults?.email_enabled)}
          >
            {channel === 'email' ? (
              <>
                <Mail className="h-4 w-4" /> Send email
              </>
            ) : (
              <>
                <MessageCircle className="h-4 w-4" /> Open WhatsApp
              </>
            )}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Tabs
          tabs={[
            { id: 'email' as Channel, label: 'Email' },
            { id: 'whatsapp' as Channel, label: 'WhatsApp' },
          ]}
          active={channel}
          onChange={setChannel}
        />

        {error && <Alert variant="error">{error}</Alert>}
        {done && (
          <Alert variant="success">
            {done.text}
            {done.link && (
              <>
                {' '}
                <a href={done.link} target="_blank" rel="noopener noreferrer" className="font-semibold underline">
                  Open WhatsApp again
                </a>
              </>
            )}
          </Alert>
        )}
        {defaults && channel === 'email' && !defaults.email_enabled && (
          <Alert variant="info">
            Email is not set up on this server, so it cannot send from here. Download the PDF and send it yourself, or
            use WhatsApp.
          </Alert>
        )}

        {channel === 'email' ? (
          <Field label="Send to" required>
            <Input
              type="email"
              multiple
              value={email}
              placeholder="accounts@client.com, second@client.com"
              onChange={(e) => setEmail(e.target.value)}
            />
            <p className="text-xs text-[color:var(--color-text-muted)]">
              Up to five addresses, separated by commas.{' '}
              {defaults?.email ? 'Filled in with the address last used for this client.' : ''}
            </p>
          </Field>
        ) : (
          <Field label="WhatsApp number" required>
            <Input
              type="tel"
              value={phone}
              placeholder="98765 43210"
              onChange={(e) => setPhone(e.target.value)}
            />
            <p className="text-xs text-[color:var(--color-text-muted)]">
              A ten-digit number is taken as an Indian mobile. For another country start with its code, like +44.
            </p>
          </Field>
        )}

        <Field label="Message" required>
          <Textarea rows={11} value={message} onChange={(e) => setMessage(e.target.value)} />
          {clientCode && (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <Select
                aria-label="Tone of the reminder"
                className="!h-8 !w-auto !py-0 text-xs"
                value={tone}
                onChange={(e) => setTone(e.target.value)}
              >
                {REMINDER_TONES.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </Select>
              <AiButton
                disabled={reword.busy || !defaults}
                title="Writes the reminder again in this tone. The amounts and bills are filled in by Orion, not by the AI."
                onClick={() => reword.run((cloudOnce) => api.reminderAi(clientCode, { tone, allow_cloud_once: cloudOnce }))}
              >
                Reword with AI
              </AiButton>
            </div>
          )}
          <AiNotice task={reword} className="mt-2" />
          {reword.phase === 'ok' && reword.result && (
            <div className="mt-2 space-y-2 rounded-xl border border-[color:var(--color-border)] p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold">Reworded message</p>
                <AiProvenance where={reword.result.where} provider={reword.result.provider} />
              </div>
              <p className="max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted px-3 py-2 text-sm">{reword.result.message}</p>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={() => {
                    setMessage(reword.result?.message ?? '')
                    reword.reset()
                  }}
                >
                  Use this message
                </Button>
                <Button size="sm" variant="ghost" onClick={reword.reset}>
                  Keep mine
                </Button>
              </div>
            </div>
          )}
          {channel === 'email' && defaults && (
            <p className="text-xs text-[color:var(--color-text-muted)]">
              Subject: {defaults.subject}
              {letterhead ? ' · The PDF is on the company letterhead.' : ''}
            </p>
          )}
        </Field>

        {defaults && defaults.history.length > 0 && (
          <div>
            <p className="text-[13px] font-medium text-[color:var(--color-text)]">Sent before</p>
            <ul className="mt-1 space-y-0.5 text-xs text-[color:var(--color-text-muted)]">
              {defaults.history.map((row, index) => (
                <li key={index}>
                  {row.kind === 'reminder' ? 'Reminder' : 'Invoice'} by {row.channel === 'email' ? 'email to' : 'WhatsApp to'}{' '}
                  {row.recipient} · {formatDay(row.sent_timestamp)}
                  {row.sent_by ? ` · ${row.sent_by}` : ''}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Modal>
  )
}
