import { CategoryBar } from '../../../components/dashboard/CategoryBar'
import { ChartCard } from '../../../components/dashboard/ChartCard'
import { MonthlyChart } from '../../../components/dashboard/MonthlyChart'
import { ReportTable } from '../../../components/dashboard/ReportTable'
import { SERIES, inr, summarizeRanked, summarizeSeries } from '../../../components/dashboard/format'
import { useTallyDashboard } from '../../TallyDashboardPage'

/** How much of what was invoiced was given back, to whom, and on which documents? */
export function TallyNotesDashboard() {
  const { series, categories, table, select, active, chip, clear } = useTallyDashboard()
  const docs = series('documents')
  const byClient = categories('notes_by_client')

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Sales invoiced vs credit notes"
        subtitle="Credit notes are drawn as positive amounts so they compare with sales. The line is net billed."
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        summary={summarizeSeries(docs, 'credit_notes')}
      >
        <MonthlyChart
          data={docs}
          bars={[
            { key: 'sales', label: 'Sales', color: SERIES.base },
            { key: 'credit_notes', label: 'Credit notes', color: SERIES.cancelled },
          ]}
          lines={[{ key: 'net', label: 'Net billed', color: SERIES.margin }]}
          selected={active('month')}
          onSelect={select('month')}
          height={280}
        />
      </ChartCard>

      <ChartCard
        quiet
        title="Credit notes by client"
        subtitle="Value given back in this selection"
        drill="Click a client"
        selection={chip('client')}
        onClear={clear('client')}
        summary={summarizeRanked(byClient)}
      >
        <CategoryBar
          data={byClient}
          selected={active('client')}
          onSelect={select('client')}
          color={SERIES.cancelled}
          format={inr}
          labelWidth={120}
          height={280}
          emptyMessage="No credit notes in this selection."
        />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-3"
        title="Credit and debit note register"
        subtitle="Every note in this selection, newest first. Credit notes are negative."
        drill="Click a client"
        selection={chip('client')}
        onClear={clear('client')}
      >
        <ReportTable
          block={table('notes')}
          exportName="tally-credit-debit-notes"
          selected={active('client')}
          onSelect={select('client')}
          searchLabel="Search client or voucher"
          hidden={['revenue', 'gst']}
          negativeTone
          emptyMessage="No credit or debit notes in this selection."
        />
      </ChartCard>
    </div>
  )
}
