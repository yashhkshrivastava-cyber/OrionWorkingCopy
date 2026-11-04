import { BankGlance } from '../../components/bank/BankGlance'
import { Bridge } from '../../components/dashboard/Bridge'
import { Fold } from '../../components/dashboard/Fold'
import { CategoryBar } from '../../components/dashboard/CategoryBar'
import { ChartCard } from '../../components/dashboard/ChartCard'
import { MonthlyChart } from '../../components/dashboard/MonthlyChart'
import { ReportTable } from '../../components/dashboard/ReportTable'
import { Section } from '../../components/dashboard/Section'
import { SERIES, inr, summarizeRanked, summarizeSeries } from '../../components/dashboard/format'
import { useDashboard } from './DashboardShell'

/** How the business is doing: earn, spend, keep, collect, and what is still owed. */
export function OverviewDashboard() {
  const { series, categories, table, select, active, chip, clear, records } = useDashboard()
  const trend = series('trend')
  const cash = series('cash')
  const clients = categories('top_clients')

  return (
    <div className="space-y-8">
      <BankGlance />
      <Section title="Performance" description="What was billed, what it cost to deliver, and what was kept.">
        <div className="grid gap-4 lg:grid-cols-3">
          <ChartCard
            quiet
            className="lg:col-span-2"
            title="Revenue, cost and margin by month"
            subtitle="Revenue against payroll plus running costs, with the margin as a share of revenue."
            drill="Click a month"
            selection={chip('month')}
            onClear={clear('month')}
            summary={summarizeSeries(trend, 'revenue')}
            records={records('bills', 'Bills')}
          >
            <MonthlyChart
              data={trend}
              bars={[
                { key: 'revenue', label: 'Revenue', color: SERIES.revenue },
                { key: 'cost', label: 'Cost', color: SERIES.expense },
              ]}
              lines={[{ key: 'margin_pct', label: 'Margin %', color: SERIES.margin, axis: 'right', format: 'percent' }]}
              selected={active('month')}
              onSelect={select('month')}
              height={310}
            />
          </ChartCard>

          <ChartCard
            quiet
            title="Where each rupee of revenue goes"
            subtitle="Revenue in this selection, less payroll and running costs, walked down to what is left."
            summary="From revenue to margin."
          >
            <Bridge parts={categories('cost_split')} height={310} />
          </ChartCard>
        </div>
      </Section>

      <Section title="Cash" description="What went out as invoices, what came back, and what is still owed.">
        <div className="grid gap-4 lg:grid-cols-3">
          <ChartCard
            quiet
            className="lg:col-span-2"
            title="Billed and collected"
            subtitle="What went out as invoices against what came in as cash. The line is collected as a share of billed."
            drill="Click a month"
            selection={chip('month')}
            onClear={clear('month')}
            summary={summarizeSeries(cash, 'collected')}
            records={records('receipts', 'Payments received')}
          >
            <MonthlyChart
              data={cash}
              bars={[
                { key: 'billed', label: 'Billed', color: SERIES.km },
                { key: 'collected', label: 'Collected', color: SERIES.committed },
              ]}
              lines={[{ key: 'rate', label: 'Collected % of billed', color: SERIES.margin, axis: 'right', format: 'percent' }]}
              selected={active('month')}
              onSelect={select('month')}
              height={280}
            />
          </ChartCard>

          <ChartCard
            quiet
            title="Money owed, by age of the bill"
            subtitle="Unpaid balance today, by how long ago the bill was raised."
            drill="Click an age"
            selection={chip('bucket')}
            onClear={clear('bucket')}
            summary={summarizeRanked(categories('ageing'))}
            records={records('receivables', 'Unpaid bills')}
          >
            <CategoryBar
              data={categories('ageing')}
              selected={active('bucket')}
              onSelect={select('bucket')}
              color={SERIES.unpaid}
              format={inr}
              labelWidth={52}
              height={280}
              emptyMessage="Nothing is owed."
            />
          </ChartCard>
        </div>
      </Section>

      <Fold keep={0} label="Show where it comes from, and the year-by-year scorecard">
      <Section title="Where it comes from" description="Which lines of business, clients and cases carry the result.">
        <div className="grid gap-4 lg:grid-cols-3">
          <ChartCard
            quiet
            className="lg:col-span-3"
            title="Business domains"
            subtitle="Revenue, margin, cash and what is owed for each line of business."
            drill="Click a domain"
            selection={chip('business_domain')}
            onClear={clear('business_domain')}
            records={records('cases', 'Cases')}
          >
            <ReportTable
              block={table('domains')}
              exportName="orion-domains"
              compact
              selected={active('business_domain')}
              onSelect={select('business_domain')}
              defaultSort={{ key: 'revenue', dir: 'desc' }}
              negativeTone
              pageSize={10}
              maxHeight={360}
            />
          </ChartCard>

          <ChartCard
            quiet
            title="Top 10 clients by revenue"
            subtitle="The ten clients that bill the most in this selection."
            drill="Click a client"
            selection={chip('client')}
            onClear={clear('client')}
            summary={summarizeRanked(clients)}
            records={records('bills', 'Bills')}
          >
            <CategoryBar
              data={clients}
              selected={active('client')}
              onSelect={select('client')}
              format={inr}
              labelWidth={140}
              height={340}
            />
          </ChartCard>

          <ChartCard
            quiet
            className="lg:col-span-2"
            title="Cases needing attention"
            subtitle="The ten cases with the thinnest margin in this selection."
            drill="Click a case"
            selection={chip('case')}
            onClear={clear('case')}
            records={records('cases', 'Cases')}
          >
            <ReportTable
              block={table('attention')}
              exportName="orion-cases-attention"
              compact
              selected={active('case')}
              onSelect={select('case')}
              negativeTone
              pageSize={10}
              maxHeight={320}
            />
          </ChartCard>
        </div>
      </Section>

      <Section
        title="Year by year"
        description="Growth, cost, margin, cash and scale for each financial year. The current year is part-way."
        collapsible
        defaultOpen={false}
      >
        <ChartCard quiet title="Financial year scorecard" drill="Click a year" selection={chip('fy')} onClear={clear('fy')}>
          <ReportTable
            block={table('fy')}
            exportName="orion-financial-years"
            compact
            selected={active('fy')}
            onSelect={select('fy')}
            defaultSort={{ key: 'fy', dir: 'asc' }}
            negativeTone
            pageSize={10}
            maxHeight={320}
          />
        </ChartCard>
      </Section>
      </Fold>
    </div>
  )
}
