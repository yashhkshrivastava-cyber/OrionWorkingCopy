import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Banknote, Camera, ChartNoAxesCombined, ClipboardCheck, Database, FileText, Gavel, MessageCircle, Plus, ReceiptText, Search, Sparkles, UserCheck, type LucideIcon } from 'lucide-react'
import { useAppearance } from '../../context/AppearanceContext'
import { useAuth } from '../../context/AuthContext'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'
import { IconTile } from '../../lumen/IconTile'
import { OPEN_WELCOME } from './events'

const KEY = (userId: number) => `orion-welcome:${userId}`
/** Anyone whose account is newer than this sees the welcome by itself the first time; everyone can open it again from Settings. */
const NEW_FOR_DAYS = 30

function seen(userId: number): boolean {
  try {
    return localStorage.getItem(KEY(userId)) === '1'
  } catch {
    return true // a browser that cannot remember would show it at every sign-in: better to stay quiet
  }
}

function markSeen(userId: number) {
  try {
    localStorage.setItem(KEY(userId), '1')
  } catch {
    // it will simply be offered again next time
  }
}

type Area = { icon: LucideIcon; hue: string; title: string; text: string; path: string }

/** What this person can reach, from their own access: the tour never shows a door they cannot open. */
function areasFor(can: Record<string, boolean | undefined>): Area[] {
  const all: [boolean | undefined, Area][] = [
    [can.dashboards, { icon: ChartNoAxesCombined, hue: 'indigo', title: 'Dashboards', text: 'Revenue, collections, margin, people and pipeline, with what changed and what to do next.', path: '/dashboard/orion' }],
    [can.ods, { icon: Database, hue: 'teal', title: 'Data', text: 'Look things up, change a record or upload from Excel.', path: '/data/orion' }],
    [can.billing, { icon: ReceiptText, hue: 'coral', title: 'Billing', text: 'Raise tax invoices, record payments, see what is owed and what is due this month.', path: '/utility/billing' }],
    [can.bank, { icon: Banknote, hue: 'green', title: 'Bank', text: 'The balance, what came in and went out, and matching the statement.', path: '/bank' }],
    [can.documents, { icon: FileText, hue: 'amber', title: 'Documents', text: 'Every paper by company, case and client, with expiry dates.', path: '/documents' }],
    [can.tenders, { icon: Gavel, hue: 'indigo', title: 'Tenders', text: 'Saved searches on GeM and MP Tenders, and the bids that match.', path: '/tenders' }],
    [can.attendance, { icon: ClipboardCheck, hue: 'teal', title: 'Attendance', text: 'Monthly registers that become salary and expenses when posted.', path: '/attendance' }],
    [true, { icon: MessageCircle, hue: 'coral', title: 'Messages', text: 'Chat with anyone or a group, send voice notes, and call with sound, video or your screen.', path: '/messages' }],
    [can.ai, { icon: Sparkles, hue: 'indigo', title: 'AI Copilot', text: 'Ask a question about the business in plain words; it only reads what you may read.', path: '/' }],
  ]
  return all.filter(([allowed]) => allowed).map(([, area]) => area)
}

function Step({ title, lead, children }: { title: string; lead: string; children: ReactNode }) {
  return (
    <div className="px-5 pb-2 pt-5 sm:px-7">
      <h3 className="font-display text-2xl font-semibold leading-tight sm:text-3xl">{title}</h3>
      <p className="mt-1.5 max-w-xl text-sm leading-relaxed text-[color:var(--color-text-muted)]">{lead}</p>
      <div className="mt-5">{children}</div>
    </div>
  )
}

/**
 * The first visit, in three short steps: pick how Orion looks (the choice is applied behind the dialog as it is made), see what you can reach
 * (only what your access allows), and a few quick ways around. It opens by itself once for an account made in the last 30 days and is
 * always there again from Settings. Skipping or finishing both count as seen; it is remembered in this browser only.
 */
export default function WelcomeTour() {
  const { user } = useAuth()
  const { prefs, setExperience } = useAppearance()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState(0)

  const userId = user?.id ?? null
  const createdMs = user?.created_timestamp ? new Date(user.created_timestamp).getTime() : NaN

  useEffect(() => {
    if (userId === null || seen(userId)) return
    const fresh = Number.isFinite(createdMs) && Date.now() - createdMs < NEW_FOR_DAYS * 86_400_000
    if (fresh) setOpen(true)
  }, [userId, createdMs])

  useEffect(() => {
    const reopen = () => {
      setStep(0)
      setOpen(true)
    }
    window.addEventListener(OPEN_WELCOME, reopen)
    return () => window.removeEventListener(OPEN_WELCOME, reopen)
  }, [])

  const close = useCallback(() => {
    if (userId !== null) markSeen(userId)
    setOpen(false)
  }, [userId])

  const areas = useMemo(
    () =>
      areasFor({
        dashboards: user?.can_orion_dashboard || user?.can_tally_dashboard,
        ods: user?.can_ods,
        billing: user?.can_billing,
        bank: user?.can_bank,
        documents: user?.can_documents,
        tenders: user?.can_tenders,
        attendance: user?.can_attendance,
        ai: user?.can_ai,
      }),
    [user],
  )

  if (!user) return null
  const first = user.display_name.split(' ')[0]
  const last = step === 2

  return (
    <Modal
      open={open}
      onClose={close}
      title={step === 0 ? `Welcome to Orion, ${first}` : 'Welcome to Orion'}
      size="xl"
      footer={
        <>
          <span className="mr-auto flex items-center gap-1.5" aria-label={`Step ${step + 1} of 3`}>
            {[0, 1, 2].map((n) => (
              <span key={n} className={`h-1.5 rounded-full transition-all ${n === step ? 'w-6 bg-primary' : 'w-1.5 bg-[color:var(--color-border-strong)]'}`} />
            ))}
          </span>
          {step === 0 && (
            <Button variant="ghost" onClick={close}>
              Skip
            </Button>
          )}
          {step > 0 && (
            <Button variant="secondary" onClick={() => setStep(step - 1)}>
              Back
            </Button>
          )}
          <Button onClick={() => (last ? close() : setStep(step + 1))}>
            {last ? 'Take me in' : 'Next'} <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        </>
      }
    >
      {step === 0 && (
        <Step title="Choose how it looks" lead="Pick the one you like. It changes everything behind this window as you choose, and you can switch back any time from the palette button at the top.">
          <div className="grid gap-3 sm:grid-cols-2" role="group" aria-label="How Orion looks">
            {(
              [
                ['lumen', 'Lumen', 'Soft glass, big headlines and cards. Calls, voice notes and groups sit beside everything else.', Sparkles],
                ['classic', 'Classic', 'The plain workspace: a side rail, tables and forms, as it has always been.', Database],
              ] as const
            ).map(([id, name, text, Icon]) => {
              const on = (prefs.experience ?? 'classic') === id
              return (
                <button
                  key={id}
                  type="button"
                  aria-pressed={on}
                  onClick={() => setExperience(id)}
                  className={`interactive flex flex-col items-start gap-3 rounded-3xl border p-5 text-left ${on ? 'border-[color:var(--color-accent)] bg-accent-dim ring-2 ring-[color:var(--color-accent)]' : 'border-[color:var(--color-border)] hover:bg-muted'}`}
                >
                  <IconTile icon={Icon} hue={id === 'lumen' ? 'indigo' : 'teal'} className="h-6 w-6" />
                  <span>
                    <span className="font-display block text-lg font-semibold">{name}</span>
                    <span className="mt-0.5 block text-sm text-[color:var(--color-text-muted)]">{text}</span>
                  </span>
                  {on && (
                    <span className="inline-flex items-center gap-1.5 text-xs font-bold text-accent">
                      <UserCheck className="h-3.5 w-3.5" aria-hidden="true" /> In use
                    </span>
                  )}
                </button>
              )
            })}
          </div>
        </Step>
      )}

      {step === 1 && (
        <Step title="What you can reach" lead="This is what your account opens. If something you need is missing, ask an administrator to switch it on.">
          <ul className="grid gap-2.5 sm:grid-cols-2">
            {areas.map(({ icon, hue, title, text, path }) => (
              <li key={title}>
                <button
                  type="button"
                  onClick={() => {
                    close()
                    navigate(path)
                  }}
                  className="interactive flex h-full w-full items-start gap-3 rounded-2xl border border-[color:var(--color-border)] p-3.5 text-left hover:bg-muted"
                >
                  <IconTile icon={icon} hue={hue} className="h-5 w-5" />
                  <span>
                    <span className="block text-sm font-bold">{title}</span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-[color:var(--color-text-muted)]">{text}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Step>
      )}

      {step === 2 && (
        <Step title="Quick ways around" lead="Four things worth knowing on your first day.">
          <ul className="space-y-2.5">
            {(
              [
                [Search, 'indigo', 'Jump anywhere', 'Press Ctrl + K (or the search box) and type a page, a bill number or a question.'],
                [Plus, 'coral', 'Make something', 'The + button at the top starts a bill, a letter, a task or a message from wherever you are.'],
                [Sparkles, 'teal', 'Ask the Copilot', 'Open it from the top bar and ask about the business in your own words.'],
                [Camera, 'amber', 'Make it yours', 'Add your photo and contact details in Settings so people know who they are talking to.'],
              ] as const
            ).map(([Icon, hue, title, text]) => (
              <li key={title} className="flex items-start gap-3 rounded-2xl border border-[color:var(--color-border)] p-3.5">
                <IconTile icon={Icon} hue={hue} className="h-5 w-5" />
                <span>
                  <span className="block text-sm font-bold">{title}</span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-[color:var(--color-text-muted)]">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </Step>
      )}
    </Modal>
  )
}
