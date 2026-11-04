import { CategoryBar } from '../../../components/dashboard/CategoryBar'
import { ChartCard } from '../../../components/dashboard/ChartCard'
import { ReportTable } from '../../../components/dashboard/ReportTable'
import { SERIES, inr, summarizeRanked } from '../../../components/dashboard/format'
import { useTallyDashboard } from '../../TallyDashboardPage'

/** What do the books say today? Balances differ in kind, so they are compared, never added up. */
export function TallyBooksDashboard() {
  const { categories, table, select, active, chip, clear } = useTallyDashboard()
  const balances = categories('position_balances')

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <ChartCard
        quiet
        title="Closing balance by bucket"
        subtitle="Each bucket on its own. Click one to list its ledgers."
        drill="Click a bucket"
        selection={chip('bucket')}
        onClear={clear('bucket')}
        summary={summarizeRanked(balances)}
      >
        <CategoryBar
          data={balances}
          selected={active('bucket')}
          onSelect={select('bucket')}
          color={SERIES.base}
          format={inr}
          labelWidth={118}
          height={Math.max(220, balances.length * 38 + 20)}
          emptyMessage="No ledgers in the warehouse."
        />
        <p className="px-4 pt-2 text-[11px] leading-snug text-[color:var(--color-text-faint)]">
          Signs follow Tally's export: debtor and bank balances arrive negative, liabilities positive. They are shown
          as stored, not converted.
        </p>
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Ledgers on the books"
        subtitle="Closing balance per ledger at the last warehouse load."
        drill="Click a bucket"
        selection={chip('bucket')}
        onClear={clear('bucket')}
      >
        <ReportTable
          block={table('position')}
          exportName="tally-books-ledgers"
          selected={active('bucket')}
          onSelect={select('bucket')}
          searchLabel="Search ledgers"
          hidden={['group']}
          pageSize={25}
          emptyMessage="No ledgers in this bucket."
        />
      </ChartCard>
    </div>
  )
}
