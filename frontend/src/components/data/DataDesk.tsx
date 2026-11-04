import { useEffect, useState, type CSSProperties } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Briefcase, Building2, Car, ChevronLeft, FileSpreadsheet, IndianRupee, Users, Landmark, Layers, Pencil, RefreshCw, Search, Target, UserPlus, UserRound, Wallet, Receipt, type LucideIcon } from 'lucide-react'
import { api } from '../../api/client'
import { IconTile } from '../../lumen/IconTile'
import { Alert } from '../ui/Alert'
import { WriteGate } from './WriteGate'

type Mode = 'create' | 'edit' | 'upload'

/** What people come here to do, in their words, and the record type that does it. The names are the ones the record forms use. */
const THINGS_TO_DO: { entity: string; title: string; hint: string; icon: LucideIcon; hue: string }[] = [
  { entity: 'Employee', title: 'Add an employee', hint: 'Name, site, pay, and their papers', icon: UserPlus, hue: 'indigo' },
  { entity: 'Client', title: 'Add a client', hint: 'A company or office we work for', icon: Building2, hue: 'teal' },
  { entity: 'Case', title: 'Add a case', hint: 'A contract or site we serve', icon: Briefcase, hue: 'coral' },
  { entity: 'Expense Transaction', title: 'Record an expense', hint: 'Something we paid, or owe, for a case', icon: Receipt, hue: 'amber' },
  { entity: 'Transaction', title: 'Record income', hint: 'Money billed or expected against a case', icon: IndianRupee, hue: 'green' },
  { entity: 'Employee Transaction', title: 'Record salary', hint: 'A month’s pay for an employee', icon: Wallet, hue: 'blue' },
  { entity: 'Contact', title: 'Add a contact', hint: 'A person at a client or a tender office', icon: UserRound, hue: 'pink' },
  { entity: 'Opportunity', title: 'Add a tender or lead', hint: 'Work we are bidding for', icon: Target, hue: 'violet' },
  { entity: 'EMD', title: 'Record an EMD', hint: 'Earnest money put up with a bid', icon: Landmark, hue: 'orange' },
  { entity: 'Car', title: 'Add a vehicle', hint: 'A car or bike the company runs', icon: Car, hue: 'slate' },
]

/** Where to look something up, grouped as the catalog groups them. */
const LOOK_UP: { label: string; names: string[] }[] = [
  { label: 'Clients and work', names: ['Client', 'Contact', 'Case', 'Opportunity'] },
  { label: 'People', names: ['Employee', 'Employee Transaction'] },
  { label: 'Money', names: ['Transaction', 'Expense Transaction', 'EMD'] },
  { label: 'Fleet', names: ['Car', 'Car Transaction'] },
  { label: 'Setup', names: ['Business Domain', 'Capability', 'Expense Type'] },
]

function Tile({ icon, hue, title, hint, onClick }: { icon: LucideIcon; hue: string; title: string; hint: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} style={{ '--hue': `var(--lumen-${hue})` } as CSSProperties} className="panel lumen-kpi interactive relative flex w-full items-center gap-4 overflow-hidden !p-4 text-left focus-visible:ring-2 focus-visible:ring-accent">
      <IconTile icon={icon} hue={hue} className="h-10 w-10" />
      <span className="relative min-w-0">
        <span className="font-display block text-base font-semibold leading-tight">{title}</span>
        <span className="t-caption mt-0.5 block text-[color:var(--color-text-muted)]">{hint}</span>
      </span>
    </button>
  )
}

/**
 * The front door of Orion data in Lumen: what a person wants to do (add an employee, record an expense), one tap to the right form, then where to look something up and, for
 * those who work with it, the warehouse. It opens the same places the plain page opens, behind the same confirmation before records can be changed.
 */
export function DataDesk({ canOds, canOdsWrite, canDw, canEtl, backToData }: { canOds: boolean; canOdsWrite: boolean; canDw: boolean; canEtl: boolean; backToData: boolean }) {
  const navigate = useNavigate()
  const [names, setNames] = useState<Set<string> | null>(null)
  // What was chosen and how (add, change or upload): it waits for the change warning before the form opens.
  const [target, setTarget] = useState<{ entity: string; mode: Mode } | undefined>(undefined)
  // Change or upload first asks which records.
  const [picking, setPicking] = useState<'edit' | 'upload' | null>(null)
  const [find, setFind] = useState('')

  useEffect(() => {
    if (!canOds) return
    api.entities().then((r) => setNames(new Set(r.entities.map((entity) => entity.name)))).catch(() => setNames(null))
  }, [canOds])

  const known = (name: string) => !names || names.has(name)
  const things = THINGS_TO_DO.filter((item) => known(item.entity) && (!find.trim() || `${item.title} ${item.hint}`.toLowerCase().includes(find.trim().toLowerCase())))
  const lookups = LOOK_UP.map((group) => ({ ...group, names: group.names.filter(known) })).filter((group) => group.names.length)

  return (
    <div className="mx-auto max-w-6xl space-y-7 pb-6">
      {backToData && (
        <Link to="/data" className="interactive inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">
          <ChevronLeft className="h-4 w-4" /> Data
        </Link>
      )}

      <section aria-label="What do you want to do" className="panel relative overflow-hidden !p-0 text-[color:var(--orion-on-primary)]" style={{ backgroundImage: 'var(--orion-highlight-fill)' }}>
        <span className="lumen-orb pointer-events-none absolute -right-10 -top-14 h-56 w-56 rounded-full bg-white/20 blur-2xl" aria-hidden="true" />
        <div className="relative space-y-4 p-6 sm:p-8">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.12em] opacity-85">Orion data</p>
            <h1 className="font-display mt-1 text-3xl font-semibold leading-tight sm:text-4xl">What do you want to do?</h1>
            <p className="mt-1 max-w-xl text-sm opacity-90">
              {canOdsWrite ? 'Choose a task and the right form opens. Nothing is saved until you check it and confirm.' : 'Look up clients, cases, people and money. You can read records here; changing them needs permission.'}
            </p>
          </div>
          {canOdsWrite && (
            <label className="relative block max-w-md rounded-full bg-white/95 text-ink shadow-card">
              <span className="sr-only">Find a task</span>
              <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[color:var(--color-text-faint)]" aria-hidden="true" />
              <input value={find} onChange={(event) => setFind(event.target.value)} placeholder="Find a task, for example expense" className="h-11 w-full rounded-full !border-0 !bg-transparent !text-ink !shadow-none" style={{ paddingLeft: '2.5rem' }} />
            </label>
          )}
        </div>
      </section>

      {canOdsWrite && (
        <section aria-label="Add or change records">
          <h2 className="t-h3 mb-3">Add something</h2>
          {things.length === 0 ? (
            <p className="rounded-2xl bg-muted px-4 py-3 text-sm text-[color:var(--color-text-muted)]">Nothing matches that. Try another word, or browse the records below.</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {things.map((item) => (
                <Tile key={item.entity} icon={item.icon} hue={item.hue} title={item.title} hint={item.hint} onClick={() => setTarget({ entity: item.entity, mode: 'create' })} />
              ))}
            </div>
          )}
        </section>
      )}

      {canOdsWrite && (
        <section aria-label="Change or upload records">
          <h2 className="t-h3 mb-3">Change what is already saved</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <Tile icon={Pencil} hue="blue" title="Change a record" hint="Correct or update something already saved" onClick={() => setPicking(picking === 'edit' ? null : 'edit')} />
            <Tile icon={FileSpreadsheet} hue="green" title="Upload from Excel" hint="Add or update many records at once from a spreadsheet" onClick={() => setPicking(picking === 'upload' ? null : 'upload')} />
          </div>
          {picking && (
            <div className="panel mt-3 !p-4" role="group" aria-label="Which records?">
              <div className="flex items-baseline justify-between gap-3">
                <p className="font-display text-base font-semibold">{picking === 'edit' ? 'Which records do you want to change?' : 'Which records is the spreadsheet for?'}</p>
                <button type="button" onClick={() => setPicking(null)} className="interactive text-sm font-semibold text-[color:var(--color-text-muted)] hover:underline">
                  Cancel
                </button>
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {lookups.map((group) => (
                  <div key={group.label}>
                    <p className="eyebrow">{group.label}</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {group.names.map((name) => (
                        <button key={name} type="button" onClick={() => { setTarget({ entity: name, mode: picking }); setPicking(null) }} className="interactive rounded-full bg-accent-dim px-3.5 py-1.5 text-sm font-semibold hover:brightness-110">
                          {name}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {canOds && (
        <section aria-label="Look something up">
          <h2 className="t-h3 mb-3">Look something up</h2>
          <div className="mb-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <Tile icon={Building2} hue="teal" title="Clients" hint="Their cases, people, bills and what they owe" onClick={() => navigate('/data/clients')} />
            <Tile icon={Briefcase} hue="coral" title="Cases" hint="A site: who works there, what it costs and what it brings" onClick={() => navigate('/data/cases')} />
            <Tile icon={Users} hue="indigo" title="Employees" hint="Who they are, where they work and who they report to" onClick={() => navigate('/data/employees')} />
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {lookups.map((group) => (
              <div key={group.label} className="panel !p-4">
                <p className="eyebrow">{group.label}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {group.names.map((name) => (
                    <button key={name} type="button" onClick={() => navigate(`/data/operational?entity=${encodeURIComponent(name)}`)} className="interactive rounded-full bg-accent-dim px-3.5 py-1.5 text-sm font-semibold text-[color:var(--color-text)] hover:brightness-110">
                      {name}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {canDw && (
        <section aria-label="Warehouse">
          <h2 className="t-h3 mb-1">For reporting</h2>
          <p className="t-caption mb-3 text-[color:var(--color-text-muted)]">The warehouse is the copy of the records the dashboards read. You only need it to check a figure or refresh the dashboards.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Tile icon={Layers} hue="amber" title="Browse the warehouse" hint="Look at the tables the dashboards use. Nothing loads from here." onClick={() => navigate('/data/warehouse')} />
            {canEtl && <Tile icon={RefreshCw} hue="coral" title="Refresh the dashboards" hint="Run the load that brings the latest records into the warehouse." onClick={() => navigate('/etl?pipeline=orion_dw')} />}
          </div>
        </section>
      )}

      {!canOds && !canOdsWrite && !canDw && <Alert variant="error">You do not have Orion data access.</Alert>}

      <WriteGate
        open={target !== undefined}
        title="Change operational data"
        body="You are opening a write workspace on live operational records. Anything you add, change, or delete is real working data. Dashboards and the warehouse stay as they are until someone loads them. Continue only if you intend to edit records."
        confirmLabel="I understand this is sensitive operational data"
        continueLabel="Continue to change records"
        onCancel={() => setTarget(undefined)}
        onContinue={() => {
          const next = target
          setTarget(undefined)
          const query = next ? `&entity=${encodeURIComponent(next.entity)}&mode=${next.mode}` : ''
          navigate(`/data/operational?intent=change${query}`, { state: { writeAck: true } })
        }}
      />
    </div>
  )
}
