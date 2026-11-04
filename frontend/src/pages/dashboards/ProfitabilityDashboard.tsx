import { CategoryBar } from '../../components/dashboard/CategoryBar'
import { CategoryDonut } from '../../components/dashboard/CategoryDonut'
import { ChartCard } from '../../components/dashboard/ChartCard'
import { Fold } from '../../components/dashboard/Fold'
import { DataGrid } from '../../components/dashboard/DataGrid'
import { Heatmap } from '../../components/dashboard/Heatmap'
import { MonthlyChart } from '../../components/dashboard/MonthlyChart'
import { PortfolioScatter, type PortfolioPoint } from '../../components/dashboard/PortfolioScatter'
import { ProfitLoss } from '../../components/dashboard/ProfitLoss'
import { ReportTable } from '../../components/dashboard/ReportTable'
import { CHART_COLORS, SERIES, inr, summarizeRanked, summarizeSeries } from '../../components/dashboard/format'
import { useDashboard } from './DashboardShell'

const pct = (value: number) => `${value.toFixed(0)}%`

/** Where the money is made and lost, and what the costs are made of. */
export function ProfitabilityDashboard() {
  const { series, categories, table, select, active, chip, clear, records } = useDashboard()
  const trend = series('trend')
  const expenseKeys = categories('expense_keys')
  const cases = table('cases')
  const points = cases.rows.map<PortfolioPoint>((r) => ({
    code: String(r.code),
    label: String(r.label),
    revenue: Number(r.revenue),
    margin_pct: Number(r.margin_pct),
    margin: Number(r.margin),
    payroll: Number(r.payroll),
  }))

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <ChartCard quiet className="lg:col-span-3" title="Profit and loss" subtitle="For the period and selection in view. Operating profit is the Operating margin above; hover a line for what it holds.">
        <ProfitLoss block={table('pnl')} />
      </ChartCard>
      <Fold keep={4}>
      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Revenue, cost and margin by month"
        subtitle="Payroll and running costs stacked against revenue, with the margin as a share of revenue"
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        summary={summarizeSeries(trend, 'margin')}
      >
        <MonthlyChart
          data={trend}
          bars={[
            { key: 'payroll', label: 'Payroll', color: SERIES.payroll, stackId: 'cost' },
            { key: 'expenses', label: 'Running costs', color: SERIES.expense, stackId: 'cost' },
          ]}
          lines={[
            { key: 'revenue', label: 'Revenue', color: SERIES.revenue },
            { key: 'margin_pct', label: 'Margin %', color: SERIES.margin, axis: 'right', format: 'percent' },
          ]}
          totalLabel="Cost"
          selected={active('month')}
          onSelect={select('month')}
          height={320}
        />
      </ChartCard>

      <ChartCard quiet title="What the cost is made of" subtitle="Payroll against running costs in this selection" summary={summarizeRanked(categories('cost_mix'))}>
        <CategoryDonut data={categories('cost_mix')} format={inr} centerLabel="Cost" height={320} colors={[SERIES.payroll, SERIES.expense]} />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Case portfolio"
        subtitle="Each dot is a case: revenue across, margin up. Dot size is payroll. Red dots lose money. Click a dot to focus the case."
        drill="Click a case"
        selection={chip('case')}
        onClear={clear('case')}
        records={records('cases', 'Cases')}
      >
        <PortfolioScatter data={points} selected={active('case')} onSelect={select('case')} height={360} />
      </ChartCard>

      <ChartCard
        quiet
        title="Cases that lose money"
        subtitle="Loss in this selection, largest first"
        drill="Click a case"
        selection={chip('case')}
        onClear={clear('case')}
        summary={summarizeRanked(categories('loss_cases'))}
      >
        <CategoryBar data={categories('loss_cases')} selected={active('case')} onSelect={select('case')} color="var(--orion-s-unpaid)" format={inr} labelWidth={150} height={360} emptyMessage="No case loses money here." />
      </ChartCard>

      <ChartCard quiet title="Margin by business domain" subtitle="Before head-office cost" drill="Click a domain" selection={chip('business_domain')} onClear={clear('business_domain')} summary={summarizeRanked(categories('margin_domain'), pct)}>
        <CategoryBar data={categories('margin_domain')} selected={active('business_domain')} onSelect={select('business_domain')} format={pct} color={SERIES.margin} labelWidth={140} height={260} />
      </ChartCard>

      <ChartCard quiet title="Margin by capability" subtitle="Before head-office cost" drill="Click a capability" selection={chip('capability')} onClear={clear('capability')} summary={summarizeRanked(categories('margin_capability'), pct)}>
        <CategoryBar data={categories('margin_capability')} selected={active('capability')} onSelect={select('capability')} format={pct} color={SERIES.margin} labelWidth={140} height={260} />
      </ChartCard>

      <ChartCard quiet className="lg:col-span-2" title="Margin by client type" subtitle="Before head-office cost" drill="Click a type" selection={chip('client_type')} onClear={clear('client_type')} summary={summarizeRanked(categories('margin_type'), pct)}>
        <CategoryBar data={categories('margin_type')} selected={active('client_type')} onSelect={select('client_type')} format={pct} color={SERIES.margin} labelWidth={80} height={260} />
      </ChartCard>

      <ChartCard quiet className="lg:col-span-2" title="Margin by business domain and year" subtitle="Margin before head-office cost, by financial year. Reading across shows a line improving or sliding.">
        <Heatmap block={table('heat_domain')} selected={active('business_domain')} onSelect={select('business_domain')} good={20} />
      </ChartCard>

      <ChartCard quiet title="Margin by capability and year" subtitle="The same view by service line">
        <Heatmap block={table('heat_capability')} selected={active('capability')} onSelect={select('capability')} good={20} />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Running costs by type"
        subtitle="The five largest expense types by month; the rest are grouped as Other"
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        records={records('expenses', 'Expenses')}
      >
        <MonthlyChart
          data={series('expense_by_type')}
          bars={expenseKeys.map((k, i) => ({ key: k.code, label: k.label, color: CHART_COLORS[i % CHART_COLORS.length], stackId: 'x' }))}
          totalLabel="Running costs"
          selected={active('month')}
          onSelect={select('month')}
          height={300}
        />
      </ChartCard>

      <ChartCard
        quiet
        title="Running costs by type"
        subtitle="Click a type to filter"
        drill="Click a type"
        selection={chip('expense_type')}
        onClear={clear('expense_type')}
        summary={summarizeRanked(categories('expense_mix'))}
        records={records('expenses', 'Expenses')}
      >
        <CategoryBar data={categories('expense_mix')} selected={active('expense_type')} onSelect={select('expense_type')} format={inr} color={SERIES.expense} labelWidth={150} height={300} />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-3"
        title="Every case"
        subtitle="Revenue, payroll, running costs and margin for each case, before head-office cost. The last row is the head-office and unallocated cost that makes the rows add up to the total margin."
        drill="Click a case"
        selection={chip('case')}
        onClear={clear('case')}
        records={records('cases', 'Cases')}
      >
        <ReportTable
          block={cases}
          exportName="orion-case-profitability"
          compact
          selected={active('case')}
          onSelect={select('case')}
          defaultSort={{ key: 'margin_pct', dir: 'asc' }}
          hidden={['domain', 'status']}
          negativeTone
          pageSize={10}
          maxHeight={460}
        />
      </ChartCard>

      <ChartCard quiet className="lg:col-span-2" title="Profit by capability" drill="Click a capability" selection={chip('capability')} onClear={clear('capability')}>
        <DataGrid block={table('capabilities')} selected={active('capability')} onSelect={select('capability')} />
      </ChartCard>

      <ChartCard quiet title="Profit by client type" drill="Click a type" selection={chip('client_type')} onClear={clear('client_type')}>
        <DataGrid block={table('client_types')} selected={active('client_type')} onSelect={select('client_type')} />
      </ChartCard>
      </Fold>
    </div>
  )
}
