import { CategoryBar } from '../../components/dashboard/CategoryBar'
import { CategoryDonut } from '../../components/dashboard/CategoryDonut'
import { ChartCard } from '../../components/dashboard/ChartCard'
import { Fold } from '../../components/dashboard/Fold'
import { MonthlyChart } from '../../components/dashboard/MonthlyChart'
import { ReportTable } from '../../components/dashboard/ReportTable'
import { CHART_COLORS, SERIES, count, inr, summarizeRanked, summarizeSeries } from '../../components/dashboard/format'
import { useDashboard } from './DashboardShell'

/** What was billed, to whom, how concentrated it is, and whether contracts bill what they should. */
export function RevenueDashboard() {
  const { series, categories, table, select, active, chip, clear, records, go } = useDashboard()
  const trend = series('trend')
  const keys = categories('capability_keys')
  const clients = categories('top_clients')

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Fold keep={3}>
      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Revenue by month and capability"
        subtitle="Each colour is a service line, stacked to the month's revenue. Click a month to focus it."
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        summary={summarizeSeries(trend, 'revenue')}
        records={records('bills', 'Bills')}
      >
        <MonthlyChart
          data={series('by_capability')}
          bars={keys.map((k, i) => ({ key: k.code, label: k.label, color: CHART_COLORS[i % CHART_COLORS.length], stackId: 'rev' }))}
          lines={[]}
          totalLabel="Revenue"
          selected={active('month')}
          onSelect={select('month')}
          height={320}
        />
      </ChartCard>

      <ChartCard
        quiet
        title="Revenue by client type"
        subtitle="Government, private and small business"
        drill="Click a type"
        selection={chip('client_type')}
        onClear={clear('client_type')}
        summary={summarizeRanked(categories('by_client_type'))}
      >
        <CategoryDonut data={categories('by_client_type')} selected={active('client_type')} onSelect={select('client_type')} centerLabel="Revenue" height={320} />
      </ChartCard>

      <ChartCard
        quiet
        title="Top clients"
        subtitle="The twelve largest relationships in this selection"
        drill="Click a client"
        selection={chip('client')}
        onClear={clear('client')}
        summary={summarizeRanked(clients)}
        records={records('bills', 'Bills')}
      >
        <CategoryBar data={clients} selected={active('client')} onSelect={select('client')} format={inr} labelWidth={150} height={360} />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-2"
        title="How concentrated is the book"
        subtitle="Largest clients with their share and the running total. The more the cumulative column climbs early, the more the business depends on a few clients."
        drill="Click a client"
        selection={chip('client')}
        onClear={clear('client')}
      >
        <ReportTable
          block={table('concentration')}
          exportName="orion-client-concentration"
          compact
          selected={active('client')}
          onSelect={select('client')}
          defaultSort={{ key: 'revenue', dir: 'desc' }}
          pageSize={10}
          maxHeight={380}
        />
      </ChartCard>

      <ChartCard quiet title="Revenue by business domain" drill="Click a domain" selection={chip('business_domain')} onClear={clear('business_domain')} summary={summarizeRanked(categories('by_domain'))}>
        <CategoryBar data={categories('by_domain')} selected={active('business_domain')} onSelect={select('business_domain')} format={inr} labelWidth={140} height={260} />
      </ChartCard>

      <ChartCard quiet title="Revenue by capability" drill="Click a capability" selection={chip('capability')} onClear={clear('capability')} summary={summarizeRanked(categories('by_capability'))}>
        <CategoryBar data={categories('by_capability')} selected={active('capability')} onSelect={select('capability')} format={inr} labelWidth={140} height={260} color={SERIES.km} />
      </ChartCard>

      <ChartCard quiet title="Revenue by state" subtitle="Where clients were based when billed" drill="Click a state" selection={chip('state')} onClear={clear('state')} summary={summarizeRanked(categories('by_state'))}>
        <CategoryBar data={categories('by_state')} selected={active('state')} onSelect={select('state')} format={inr} labelWidth={110} height={260} color={SERIES.days} />
      </ChartCard>

      <ChartCard quiet title="Revenue by client priority" subtitle="P1 is the most important tier" drill="Click a tier" selection={chip('priority')} onClear={clear('priority')} summary={summarizeRanked(categories('by_priority'))}>
        <CategoryBar data={categories('by_priority')} selected={active('priority')} onSelect={select('priority')} format={inr} labelWidth={40} height={200} color={SERIES.committed} />
      </ChartCard>

      <ChartCard
        quiet
        title="Who is growing the book"
        subtitle="Revenue by how long the client has been billed: first year, one to two years, or longer"
        summary={summarizeRanked(categories('vintage'))}
      >
        <CategoryDonut data={categories('vintage')} format={inr} centerLabel="Revenue" height={230} />
      </ChartCard>

      <ChartCard quiet title="Bills by size" subtitle="How many invoices fall in each band" summary={summarizeRanked(categories('bill_size'), count)}>
        <CategoryBar data={categories('bill_size')} format={count} labelWidth={96} height={230} color={SERIES.base} />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-3"
        title="Contracts billing below or above what they expect"
        subtitle="Active cases: the contract value each month against what was billed in the last three months. A positive gap is under-billing; negative is billing above the contract figure."
        drill="Click a case"
        selection={chip('case')}
        onClear={clear('case')}
        records={records('cases', 'Cases')}
      >
        <ReportTable
          block={table('contract_gap')}
          exportName="orion-contract-gap"
          compact
          selected={active('case')}
          onSelect={select('case')}
          defaultSort={{ key: 'gap', dir: 'desc' }}
          negativeTone
          pageSize={10}
          maxHeight={380}
        />
      </ChartCard>

      <ChartCard quiet className="lg:col-span-3" title="Latest bills" subtitle="The fifteen most recent in this selection. Click a bill to open it." records={records('bills', 'Bills')}>
        <ReportTable
          block={table('recent_bills')}
          exportName="orion-latest-bills"
          onOpen={(code) => go(`/utility/billing/${encodeURIComponent(code)}`)}
          pageSize={15}
          maxHeight={420}
        />
      </ChartCard>
      </Fold>
    </div>
  )
}
