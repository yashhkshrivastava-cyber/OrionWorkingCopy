import { CategoryBar } from '../../../components/dashboard/CategoryBar'
import { ChartCard } from '../../../components/dashboard/ChartCard'
import { MonthlyChart } from '../../../components/dashboard/MonthlyChart'
import { SERIES, inr, summarizeRanked, summarizeSeries } from '../../../components/dashboard/format'
import { useTallyDashboard } from '../../TallyDashboardPage'

/** Is billing growing, and who is it coming from? */
export function TallyOverviewDashboard() {
  const { series, categories, select, active, chip, clear } = useTallyDashboard()
  const trend = series('trend')
  const clients = categories('top_clients').slice(0, 10)
  const income = categories('income_mix')

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <ChartCard
        quiet
        className="lg:col-span-3"
        title="Monthly billing trend"
        subtitle="Revenue plus GST by month. The dashed line is the average month in view. Click a month to focus it."
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        summary={summarizeSeries(trend, 'billed')}
      >
        <MonthlyChart
          data={trend}
          bars={[
            { key: 'revenue', label: 'Revenue ex GST', color: SERIES.base, stackId: 'billed' },
            { key: 'gst', label: 'GST', color: SERIES.expected, stackId: 'billed' },
          ]}
          average={{ key: 'billed', label: 'Average month' }}
          totalLabel="Revenue + GST"
          selected={active('month')}
          onSelect={select('month')}
          height={280}
        />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Top 10 clients by revenue"
        subtitle="Revenue ex GST in this selection. Click a client to filter the page."
        drill="Click a client"
        selection={chip('client')}
        onClear={clear('client')}
        summary={summarizeRanked(clients)}
      >
        <CategoryBar
          data={clients}
          selected={active('client')}
          onSelect={select('client')}
          color={SERIES.base}
          format={inr}
          labelWidth={150}
          height={320}
        />
      </ChartCard>

      <ChartCard
        quiet
        title="Where the income comes from"
        subtitle="Revenue by Tally income line"
        drill="Click a line"
        selection={chip('income_line')}
        onClear={clear('income_line')}
        summary={summarizeRanked(income)}
      >
        <CategoryBar
          data={income}
          selected={active('income_line')}
          onSelect={select('income_line')}
          color={SERIES.km}
          format={inr}
          labelWidth={92}
          height={320}
          emptyMessage="No income lines in this selection."
        />
      </ChartCard>
    </div>
  )
}
