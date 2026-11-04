import { CategoryBar } from '../../../components/dashboard/CategoryBar'
import { ChartCard } from '../../../components/dashboard/ChartCard'
import { MonthlyChart } from '../../../components/dashboard/MonthlyChart'
import { ReportTable } from '../../../components/dashboard/ReportTable'
import { SERIES, inr, summarizeRanked, summarizeSeries } from '../../../components/dashboard/format'
import { useTallyDashboard } from '../../TallyDashboardPage'

/** What is the revenue made of, and is the mix shifting? */
export function TallyIncomeDashboard() {
  const { series, categories, table, select, active, chip, clear } = useTallyDashboard()
  const income = series('income')
  const groups = categories('income_mix')

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Monthly income by line"
        subtitle="Income ledger postings on sales documents, stacked so the whole month and its mix read together."
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        summary={summarizeSeries(
          income.map((point) => ({
            ...point,
            total: ['manpower', 'vehicle', 'service', 'other_income'].reduce((sum, key) => sum + Number(point[key] || 0), 0),
          })),
          'total',
        )}
      >
        <MonthlyChart
          data={income}
          bars={[
            { key: 'manpower', label: 'Manpower', color: SERIES.base, stackId: 'inc' },
            { key: 'vehicle', label: 'Vehicle rent', color: SERIES.km, stackId: 'inc' },
            { key: 'service', label: 'SG service', color: SERIES.tax, stackId: 'inc' },
            { key: 'other_income', label: 'Other', color: SERIES.payroll, stackId: 'inc' },
          ]}
          totalLabel="Income"
          selected={active('month')}
          onSelect={select('month')}
          height={280}
        />
      </ChartCard>

      <ChartCard
        quiet
        title="Income by line"
        subtitle="Total in this selection. Click a line to filter."
        drill="Click a line"
        selection={chip('income_line')}
        onClear={clear('income_line')}
        summary={summarizeRanked(groups)}
      >
        <CategoryBar
          data={groups}
          selected={active('income_line')}
          onSelect={select('income_line')}
          color={SERIES.base}
          format={inr}
          labelWidth={92}
          height={280}
          emptyMessage="No income lines in this selection."
        />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-3"
        title="Income ledgers"
        subtitle="Each Tally income account in this selection. Click a row to keep that ledger."
        drill="Click a ledger"
        selection={chip('income_line')}
        onClear={clear('income_line')}
      >
        <ReportTable
          block={table('income_ledgers')}
          exportName="tally-income-ledgers"
          selected={active('income_line')}
          onSelect={select('income_line')}
          searchLabel="Search ledgers"
          defaultSort={{ key: 'revenue', dir: 'desc' }}
          emptyMessage="No income ledger lines in this selection."
        />
      </ChartCard>
    </div>
  )
}
