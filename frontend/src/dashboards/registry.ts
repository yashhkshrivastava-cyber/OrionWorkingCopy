import {
  Building2,
  Car,
  HandCoins,
  IndianRupee,
  Landmark,
  LayoutDashboard,
  PieChart,
  ShieldCheck,
  Target,
  TrendingDown,
  TrendingUp,
  Users,
  Wallet,
  type LucideIcon,
} from 'lucide-react'

/** The dashboards in the order they appear in the tab strip. */
export type DashboardTab = {
  /** Matches the backend view name. */
  view: string
  /** Route segment under /dashboard/orion; the overview sits at /dashboard/orion itself. */
  path: string
  label: string
  title: string
  subtitle: string
  icon: LucideIcon
  /** A tab with its own page and data, outside the dashboard shell (the forecast): it has no backend view of the same name. */
  standalone?: boolean
}

/** An Orion tab: which figures head it and which record sets are worth opening from it. */
export type OrionDashboardTab = DashboardTab & {
  kpiKeys: string[]
  /** Record sets offered in the "Explore records" menu, most relevant first. */
  records: string[]
}

export const DASHBOARDS: OrionDashboardTab[] = [
  {
    view: 'overview',
    path: '',
    label: 'Overview',
    title: 'Executive overview',
    subtitle:
      'Revenue, delivery cost, margin, cash and the money still owed: how the business is doing and where to look next.',
    icon: LayoutDashboard,
    kpiKeys: ['revenue', 'margin', 'margin_pct', 'collected', 'outstanding', 'overdue_90', 'active_cases', 'headcount'],
    records: ['bills', 'cases', 'receivables'],
  },
  {
    view: 'revenue',
    path: 'revenue',
    label: 'Revenue',
    title: 'Revenue and billing',
    subtitle: 'What was billed, to whom, how concentrated it is, and whether contracts are billing what they should.',
    icon: IndianRupee,
    kpiKeys: ['revenue', 'billed', 'credit_notes', 'gst', 'bills', 'avg_bill', 'clients', 'cases_billed', 'run_rate'],
    records: ['bills', 'cases'],
  },
  {
    view: 'collections',
    path: 'collections',
    label: 'Collections',
    title: 'Collections and receivables',
    subtitle: 'Cash coming in, what clients still owe, how old it is, and who is slow to pay.',
    icon: HandCoins,
    kpiKeys: ['outstanding', 'overdue_90', 'dso', 'collected', 'tds_held', 'collection_rate', 'days_to_collect', 'open_bills', 'billed'],
    records: ['receivables', 'receipts', 'bills'],
  },
  {
    view: 'profitability',
    path: 'profitability',
    label: 'Profitability',
    title: 'Profit and cost',
    subtitle: 'The profit and loss, and where the money is made and lost: margin by case, client and business line, and what the costs are made of.',
    icon: PieChart,
    kpiKeys: ['revenue', 'cost', 'margin', 'margin_pct', 'payroll_pct', 'expense_pct', 'rev_per_head', 'fleet_cost'],
    records: ['cases', 'expenses', 'payroll'],
  },
  {
    view: 'people',
    path: 'people',
    label: 'People',
    title: 'People and payroll',
    subtitle: 'Headcount, joiners and leavers, payroll cost, how staff are spread across cases, and who is still to be paid.',
    icon: Users,
    kpiKeys: ['headcount', 'heads', 'payroll', 'rev_per_head', 'attrition', 'salary_pending', 'days_worked', 'payroll_pct'],
    records: ['employees', 'payroll'],
  },
  {
    view: 'pipeline',
    path: 'pipeline',
    label: 'Pipeline',
    title: 'Tenders and pipeline',
    subtitle: 'Opportunities by stage, how often they are won, why they are lost, what the wins now bill, and the earnest money still to come back.',
    icon: Target,
    kpiKeys: ['opps', 'open_pipeline', 'won', 'win_rate', 'cycle_days', 'pipeline_staff', 'emd_held', 'emd_overdue', 'emd_lost'],
    records: ['opportunities', 'cases', 'emds'],
  },
  {
    view: 'fleet',
    path: 'fleet',
    label: 'Fleet',
    title: 'Fleet and travel',
    subtitle: 'Distance driven, what it costs, which cars and drivers carry it, and whether cases stay inside their allowance.',
    icon: Car,
    kpiKeys: ['km', 'fleet_cost', 'cost_per_km', 'cars_active', 'km_per_day'],
    records: ['fleet', 'cases'],
  },
  {
    view: 'controls',
    path: 'controls',
    label: 'Controls',
    title: 'Controls and risk',
    subtitle: 'Cancelled and edited bills, GST, EPFO and ESIC not yet paid, salary pending, active cases that have not been billed, and client relationships that need a call.',
    icon: ShieldCheck,
    kpiKeys: ['cancelled_bills', 'edited_bills', 'gst_unpaid', 'epf_unpaid', 'esic_unpaid', 'itc', 'net_gst', 'salary_pending', 'unbilled_cases', 'open_bills', 'clients_no_contact', 'contact_follow_ups'],
    records: ['bills', 'receivables', 'payroll', 'contacts'],
  },
  {
    // Read from the Bank module, not the warehouse; only people with Bank access are shown it (DashboardShell).
    view: 'cash',
    path: 'cash',
    label: 'Cash',
    title: 'Cash and bank',
    subtitle: 'The bank balance, what came in and went out, interest and other income, and where the balance is heading.',
    icon: Wallet,
    kpiKeys: ['bank_balance', 'bank_in', 'bank_out', 'bank_net', 'bank_other_income', 'bank_unreconciled', 'bank_next30'],
    records: [],
  },
  {
    // Statistics over every month of history, on its own page (ForecastPage); the period filters of the other tabs do not apply to it.
    view: 'forecast',
    path: 'forecast',
    label: 'Forecast',
    title: 'Forecast',
    subtitle: 'Where the next month, quarter, half-year, year and three years are heading at the present pace.',
    icon: TrendingUp,
    standalone: true,
    kpiKeys: [],
    records: [],
  },
]

export const dashboardByView = (view: string): OrionDashboardTab =>
  DASHBOARDS.find((tab) => tab.view === view) ?? DASHBOARDS[0]

/** Tally warehouse tabs. Same chrome as Orion, billed/books facts only. */
export type TallyDashboardTab = DashboardTab & {
  kpiKeys: string[]
  /** Which insight areas the tab shows under its figures. */
  areas: ('trend' | 'clients' | 'notes' | 'income')[]
  /** Closing balances: the period and billing filters do not apply. */
  snapshot?: boolean
}

export const TALLY_DASHBOARDS: TallyDashboardTab[] = [
  {
    view: 'overview',
    path: '',
    label: 'Overview',
    title: 'Billing overview',
    subtitle: 'How much was billed, whether it is growing, and which clients drive it.',
    icon: LayoutDashboard,
    kpiKeys: ['billed', 'revenue', 'gst', 'invoices', 'clients', 'debtors'],
    areas: ['trend', 'clients', 'notes', 'income'],
  },
  {
    view: 'billing',
    path: 'billing',
    label: 'Billing',
    title: 'Billing activity',
    subtitle: 'How many documents went out, how large they were, and how billing splits by year.',
    icon: IndianRupee,
    kpiKeys: ['avg_invoice', 'mom_revenue', 'gst_pct', 'sales', 'credit_notes', 'latest_month'],
    areas: ['trend'],
  },
  {
    view: 'notes',
    path: 'credit-notes',
    label: 'Credit notes',
    title: 'Credit and debit notes',
    subtitle: 'Sales invoiced, what was given back through credit notes, and the net billed.',
    icon: TrendingDown,
    kpiKeys: ['sales', 'credit_notes', 'cn_rate', 'debit_notes', 'billed', 'invoices'],
    areas: ['notes'],
  },
  {
    view: 'income',
    path: 'income',
    label: 'Income',
    title: 'Income mix',
    subtitle: 'Manpower, vehicle rent, and service income from Tally ledgers.',
    icon: PieChart,
    kpiKeys: ['manpower', 'vehicle', 'service', 'other_income', 'revenue', 'gst'],
    areas: ['income'],
  },
  {
    view: 'clients',
    path: 'clients',
    label: 'Clients',
    title: 'Clients and debtors',
    subtitle: 'Who was billed, concentration, and Sundry Debtor closing.',
    icon: Building2,
    kpiKeys: ['clients', 'top_share', 'debtors', 'billed', 'invoices', 'latest_month'],
    areas: ['clients'],
  },
  {
    view: 'books',
    path: 'books',
    label: 'Books',
    title: 'Books snapshot',
    subtitle: 'Closing balances at the last warehouse load, not a billed period.',
    icon: Landmark,
    kpiKeys: ['gst_payable', 'loans', 'creditors', 'statutory', 'cash', 'profit_loss'],
    areas: [],
    snapshot: true,
  },
  {
    view: 'forecast',
    path: 'forecast',
    label: 'Forecast',
    title: 'Billing forecast',
    subtitle: 'Where billing is heading over the next month, quarter, half-year, year and three years.',
    icon: TrendingUp,
    standalone: true,
    kpiKeys: [],
    areas: [],
  },
]

export const tallyDashboardByView = (view: string): TallyDashboardTab =>
  TALLY_DASHBOARDS.find((tab) => tab.view === view) ?? TALLY_DASHBOARDS[0]
