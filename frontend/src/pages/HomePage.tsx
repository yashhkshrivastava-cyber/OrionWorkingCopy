import { MapPin, Shield, Sparkles, Users, Monitor, SprayCan, Clock, Award, FileCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { BrandMark } from '../components/BrandMark'

const SERVICES = [
  {
    title: 'Security officers',
    copy: 'Trained personnel for offices, campuses, and events — present, alert, and professional on every shift.',
    image: '/images/prakash-guards.png',
    alt: 'Security officers at a corporate entrance',
  },
  {
    title: 'Housekeeping & cleaning',
    copy: 'Daily upkeep for offices, institutions, and facilities. Neat, discreet, and on a schedule you can count on.',
    image: '/images/prakash-cleaning.png',
    alt: 'Housekeeping staff maintaining an office corridor',
  },
  {
    title: 'Computer operators',
    copy: 'Front-desk and back-office operators who keep attendance, records, and day-to-day systems moving.',
    image: '/images/prakash-operators.png',
    alt: 'Computer operators at workstations',
  },
]

const MORE_SERVICES = [
  {
    title: 'Guards & watch',
    copy: 'Gate, patrol, and night coverage for sites that need a reliable presence around the clock.',
    icon: Shield,
  },
  {
    title: 'Unskilled manpower',
    copy: 'Cleaning crews, helpers, and general staff — screened, briefed, and ready to deploy.',
    icon: SprayCan,
  },
  {
    title: 'Skilled manpower',
    copy: 'Operators, supervisors, and specialised support staff matched to the work on the ground.',
    icon: Monitor,
  },
]

const STATS = [
  { value: 'Madhya Pradesh', label: 'Active across the state — cities, campuses, and sites well beyond one district' },
  { value: 'National tenders', label: 'Set up to bid and deploy wherever the contract is awarded' },
  { value: 'Skilled + unskilled', label: 'One partner for security, housekeeping, and office support' },
]

const CLIENTS = [
  { name: 'Horizon Retail', initials: 'HR', sector: 'Retail', tone: 'from-brand-600 to-brand-800' },
  { name: 'Narmada Care', initials: 'NC', sector: 'Healthcare', tone: 'from-brand-500 to-brand-900' },
  { name: 'Fortview Hotels', initials: 'FH', sector: 'Hospitality', tone: 'from-alt-500 to-alt-900' },
  { name: 'Sanchi Finance', initials: 'SF', sector: 'Banking', tone: 'from-alt-500 to-alt-800' },
  { name: 'Vidya Niketan', initials: 'VN', sector: 'Education', tone: 'from-brand-400 to-alt-800' },
  { name: 'Malwa Industries', initials: 'MI', sector: 'Manufacturing', tone: 'from-alt-600 to-brand-900' },
  { name: 'Chambal Logistics', initials: 'CL', sector: 'Logistics', tone: 'from-brand-600 to-brand-900' },
  { name: 'Aahilya Estates', initials: 'AE', sector: 'Residential', tone: 'from-alt-600 to-alt-900' },
  { name: 'Kila Campus', initials: 'KC', sector: 'Campus', tone: 'from-brand-500 to-alt-900' },
  { name: 'Riverbend Mills', initials: 'RM', sector: 'Industry', tone: 'from-positive to-brand-900' },
]

const CLIENTS_B = [
  { name: 'City Square Mall', initials: 'CS', sector: 'Retail', tone: 'from-amber to-alt-800' },
  { name: 'Saraswati School', initials: 'SS', sector: 'Education', tone: 'from-alt-500 to-alt-900' },
  { name: 'Taj-e-Mahal Club', initials: 'TC', sector: 'Hospitality', tone: 'from-brand-600 to-alt-900' },
  { name: 'Betwa Bank House', initials: 'BB', sector: 'Banking', tone: 'from-alt-500 to-brand-800' },
  { name: 'Green Park Residency', initials: 'GP', sector: 'Residential', tone: 'from-brand-500 to-alt-900' },
  { name: 'Udyog Vihar', initials: 'UV', sector: 'Industrial', tone: 'from-alt-700 to-brand-950' },
  { name: 'Maya Hospital', initials: 'MH', sector: 'Healthcare', tone: 'from-brand-500 to-brand-900' },
  { name: 'North Gate Offices', initials: 'NG', sector: 'Corporate', tone: 'from-brand-500 to-brand-950' },
]

function greeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

function ClientCard({
  name,
  initials,
  sector,
  tone,
}: {
  name: string
  initials: string
  sector: string
  tone: string
}) {
  return (
    <div className="data-hot flex w-[17.5rem] shrink-0 items-center gap-3 rounded-2xl border border-[color:var(--color-border)] bg-surface/80 px-4 py-3 shadow-card backdrop-blur-sm">
      <div
        className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br text-sm font-bold tracking-wide text-ink shadow-inner transition-transform duration-300 hover:scale-110 ${tone}`}
      >
        {initials}
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-[color:var(--color-text)]">{name}</p>
        <p className="text-xs text-[color:var(--color-text-muted)]">{sector}</p>
      </div>
    </div>
  )
}

function MarqueeRow({
  items,
  reverse = false,
}: {
  items: typeof CLIENTS
  reverse?: boolean
}) {
  const loop = [...items, ...items]
  return (
    <div className="marquee">
      <div className={`marquee-track ${reverse ? 'reverse' : ''}`}>
        {loop.map((client, index) => (
          <ClientCard key={`${client.initials}-${index}`} {...client} />
        ))}
      </div>
    </div>
  )
}

export function HomePage() {
  const { user } = useAuth()
  const firstName = user?.display_name?.split(' ')[0]

  return (
    <div className="overflow-x-hidden pb-[max(1rem,env(safe-area-inset-bottom))]">
      <section data-photo className="relative isolate min-h-[min(88vh,52rem)] overflow-hidden">
        <img
          src="/images/prakash-hero.png"
          alt="Prakash Securities team at a campus entrance"
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-r from-ink/90 via-ink/70 to-ink/35" />
        <div className="absolute inset-0 bg-gradient-to-t from-ink/80 via-transparent to-ink/30" />

        <div className="relative mx-auto flex min-h-[min(88vh,52rem)] max-w-6xl flex-col justify-end px-5 pb-14 pt-16 sm:px-8 sm:pb-20">
          <p className="mb-5 inline-flex w-fit items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-xs font-medium text-white/90 backdrop-blur-md">
            <Sparkles className="h-3.5 w-3.5" />
            {user ? `${greeting()}, ${firstName}` : 'Welcome to Prakash Securities'}
          </p>
          <p className="mb-3 inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.22em] text-rail-accent">
            <MapPin className="h-3.5 w-3.5" />
            Madhya Pradesh · National tenders
          </p>
          <BrandMark size={52} className="mb-4 drop-shadow-lg" />
          <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-white sm:text-5xl lg:text-6xl">
            Prakash Securities
          </h1>
          <p className="mt-4 max-w-xl text-lg leading-relaxed text-slate-200 sm:text-xl">
            Manpower you can stand behind — skilled and unskilled people for security, cleaning, guards, computer
            operators, and the everyday work that keeps a site running. We work across Madhya Pradesh and take on
            national tenders.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <a
              href="#work"
              className="interactive rounded-xl bg-rail-accent px-5 py-2.5 text-sm font-semibold text-ink shadow-raised hover:brightness-110"
            >
              See our work
            </a>
            {user ? (
              <Link
                to="/dashboard"
                className="interactive rounded-xl border border-white/25 bg-white/10 px-5 py-2.5 text-sm font-medium text-white backdrop-blur-md hover:bg-white/15"
              >
                Open workspace
              </Link>
            ) : (
              <Link
                to="/login"
                className="interactive rounded-xl border border-white/25 bg-white/10 px-5 py-2.5 text-sm font-medium text-white backdrop-blur-md hover:bg-white/15"
              >
                Sign in
              </Link>
            )}
            <a
              href="#clients"
              className="interactive rounded-xl border border-white/25 bg-white/10 px-5 py-2.5 text-sm font-medium text-white backdrop-blur-md hover:bg-white/15"
            >
              Clients we serve
            </a>
          </div>
        </div>
      </section>

      <section className="relative z-10 mx-auto -mt-8 grid max-w-6xl gap-3 px-4 sm:grid-cols-3 sm:px-8">
        {STATS.map((stat) => (
          <div
            key={stat.value}
            className="panel data-hot p-5"
          >
            <p className="text-lg font-semibold tracking-tight">{stat.value}</p>
            <p className="mt-1 text-sm leading-relaxed text-[color:var(--color-text-muted)]">{stat.label}</p>
          </div>
        ))}
      </section>

      <section id="work" className="mx-auto max-w-6xl scroll-mt-20 px-5 py-16 sm:px-8 sm:py-20">
        <div className="grid gap-10 lg:grid-cols-[1.1fr_0.9fr] lg:items-center">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">
              About us
            </p>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
              Statewide in Madhya Pradesh. Ready for national work.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-[color:var(--color-text-muted)]">
              Prakash Securities is a manpower company from Madhya Pradesh. We place both skilled and unskilled
              workers — security staff, cleaning crews, guards, computer operators, and similar roles — with
              organisations that need a dependable team on the floor, not just a contract on paper.
            </p>
            <p className="mt-3 text-base leading-relaxed text-[color:var(--color-text-muted)]">
              Our work runs across MP, and we also bid on national tenders when the site sits outside the state. We
              brief every person before they go on site and stay reachable when a shift needs covering. The work is
              simple: send the right people, keep the standard, and treat every client’s premises as if they were our
              own.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {[
              { icon: Users, title: 'Screened people', copy: 'Staff selected for the role, not just a headcount.' },
              { icon: Clock, title: 'Shift-ready', copy: 'Day, night, and rotating coverage when the site needs it.' },
              { icon: Award, title: 'On-ground standard', copy: 'Uniform, conduct, and reporting that hold up in public.' },
              { icon: FileCheck, title: 'Tender-ready', copy: 'Set up for MP contracts and national tenders, then staff the site.' },
            ].map((item) => {
              const Icon = item.icon
              return (
                <div
                  key={item.title}
                  className="data-hot group rounded-2xl border border-[color:var(--color-border)] bg-surface p-4"
                >
                  <Icon className="mb-2 h-5 w-5 text-accent transition-transform duration-200 group-hover:scale-110" />
                  <p className="text-sm font-semibold">{item.title}</p>
                  <p className="mt-1 text-xs leading-relaxed text-[color:var(--color-text-muted)]">{item.copy}</p>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      <section className="py-4">
        <div className="mx-auto max-w-6xl px-5 sm:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">
            What we provide
          </p>
          <h2 className="mt-2 max-w-2xl text-3xl font-semibold tracking-tight sm:text-4xl">
            The roles organisations ask us for, again and again.
          </h2>
        </div>

        <div className="mx-auto mt-10 grid max-w-6xl gap-5 px-5 sm:px-8 lg:grid-cols-3">
          {SERVICES.map((service) => (
            <article
              key={service.title}
              className="panel data-hot group overflow-hidden"
            >
              <div data-photo className="relative h-56 overflow-hidden">
                <img
                  src={service.image}
                  alt={service.alt}
                  className="h-full w-full object-cover transition duration-500 group-hover:scale-105"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-ink/70 to-transparent" />
                <h3 className="absolute bottom-4 left-4 right-4 text-lg font-semibold text-white">{service.title}</h3>
              </div>
              <p className="p-5 text-sm leading-relaxed text-[color:var(--color-text-muted)]">{service.copy}</p>
            </article>
          ))}
        </div>

        <div className="mx-auto mt-5 grid max-w-6xl gap-4 px-5 pb-16 sm:grid-cols-3 sm:px-8">
          {MORE_SERVICES.map((service) => {
            const Icon = service.icon
            return (
              <div
                key={service.title}
                className="data-hot group rounded-2xl border border-[color:var(--color-border)] bg-surface/80 p-5"
              >
                <Icon className="mb-3 h-5 w-5 text-accent transition-transform duration-200 group-hover:scale-110" />
                <h3 className="text-sm font-semibold">{service.title}</h3>
                <p className="mt-1 text-sm leading-relaxed text-[color:var(--color-text-muted)]">{service.copy}</p>
              </div>
            )
          })}
        </div>
      </section>

      <section id="clients" className="scroll-mt-20 py-16 sm:py-20">
        <div className="mx-auto mb-10 max-w-6xl px-5 sm:px-8">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">
            Clients
          </p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
            Trusted across sites like these.
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-[color:var(--color-text-muted)]">
            A preview of the industries we cover — malls, hospitals, campuses, factories, and offices across Madhya
            Pradesh, and on contracts won through national tenders. Real client names and logos will replace these
            placeholders when you share them.
          </p>
        </div>

        <div className="space-y-4">
          <MarqueeRow items={CLIENTS} />
          <MarqueeRow items={CLIENTS_B} reverse />
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 pb-20 sm:px-8">
        <div className="relative overflow-hidden rounded-2xl bg-rail px-6 py-12 text-rail-strong sm:px-12">
          <div className="pointer-events-none absolute -right-16 -top-16 h-56 w-56 rounded-full bg-rail-accent/20 blur-3xl" />
          <div className="relative max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-rail-accent">
              Madhya Pradesh and beyond
            </p>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight">
              When a site needs people, we send ours.
            </h2>
            <p className="mt-3 text-sm leading-relaxed text-rail-text">
              Prakash Securities places security, housekeeping, guards, computer operators, and related manpower —
              skilled and unskilled — with organisations across Madhya Pradesh, and on national tenders anywhere the
              work is awarded.
            </p>
          </div>
        </div>
      </section>
    </div>
  )
}
