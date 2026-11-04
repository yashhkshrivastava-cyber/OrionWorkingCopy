import { Link } from 'react-router-dom'
import { Landmark } from 'lucide-react'
import { CategoryBar } from '../../components/dashboard/CategoryBar'
import { ChartCard } from '../../components/dashboard/ChartCard'
import { Fold } from '../../components/dashboard/Fold'
import { MonthlyChart } from '../../components/dashboard/MonthlyChart'
import { ReportTable } from '../../components/dashboard/ReportTable'
import { SERIES, inr, summarizeSeries } from '../../components/dashboard/format'
import { EmptyState } from '../../components/ui/EmptyState'
import { useDashboard } from './DashboardShell'

/** The bank on the dashboards: the balance and its movements for the period chosen, interest and other income, and what is coming. Read from the Bank book. */
export function CashDashboard() {
  const { series, categories, table, active, select, chip, clear } = useDashboard()
  const trend = series('trend')

  if (!trend.length) {
    return (
      <EmptyState icon={Landmark} title="The bank account is not set up yet">
        Enter the opening balance on the{' '}
        <Link to="/bank/account" className="text-accent hover:underline">
          Bank page
        </Link>{' '}
        and this tab fills in: the balance, what came in and went out, interest and other income, and where the balance is heading.
      </EmptyState>
    )
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Fold keep={5}>
      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Money in, money out and the balance"
        subtitle="Each month’s receipts and payments in the bank, with the balance at the end of the month on the right-hand scale."
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        summary={summarizeSeries(trend, 'money_in')}
      >
        <MonthlyChart
          data={trend}
          bars={[
            { key: 'money_in', label: 'Money in', color: SERIES.joiners },
            { key: 'money_out', label: 'Money out', color: SERIES.expense },
          ]}
          lines={[{ key: 'closing_balance', label: 'Balance at month end', color: SERIES.margin, axis: 'right' }]}
          rightFormat="money"
          selected={active('month')}
          onSelect={select('month')}
          height={310}
        />
      </ChartCard>

      <ChartCard
        quiet
        title="Interest and other income"
        subtitle="Earnings that are not clients’ payments: interest the bank paid, and other income recorded on the Bank page."
        summary={summarizeSeries(trend, 'other_income')}
      >
        <MonthlyChart
          data={trend}
          bars={[{ key: 'other_income', label: 'Interest and other income', color: SERIES.gst }]}
          lines={[{ key: 'interest', label: 'of which interest', color: SERIES.revenue }]}
          height={310}
          emptyMessage="No interest or other income in this period."
        />
      </ChartCard>

      <ChartCard quiet title="Where the money came from" subtitle="Receipts in this period, by kind.">
        <CategoryBar data={categories('inflow')} color={SERIES.joiners} format={inr} labelWidth={110} height={280} emptyMessage="Nothing received in this period." />
      </ChartCard>
      <ChartCard quiet title="Where the money went" subtitle="Payments in this period, by kind.">
        <CategoryBar data={categories('outflow')} color={SERIES.expense} format={inr} labelWidth={130} height={280} emptyMessage="Nothing paid out in this period." />
      </ChartCard>
      <ChartCard quiet title="Projected balance, week by week" subtitle="From what Orion already expects: bills yet to be paid, costs to come and GST to pay. Overdue money is left out.">
        <ReportTable block={table('weeks')} exportName="orion-cash-forecast" pageSize={13} maxHeight={320} />
      </ChartCard>

      <ChartCard quiet className="lg:col-span-3" title="Interest and other income received" subtitle="Each receipt in this period that is not a client’s payment.">
        <ReportTable block={table('income')} exportName="orion-interest-and-other-income" pageSize={10} maxHeight={360} />
      </ChartCard>

      <div className="grid gap-4 lg:col-span-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 30rem), 1fr))' }}>
        <ChartCard quiet title="Coming up" subtitle="The next movements Orion expects, soonest first.">
          <ReportTable block={table('expected')} exportName="orion-cash-expected" pageSize={10} maxHeight={360} />
        </ChartCard>
        <ChartCard quiet title="Overdue" subtitle="Expected before today and not yet recorded as received or paid.">
          <ReportTable block={table('overdue')} exportName="orion-cash-overdue" pageSize={10} maxHeight={360} />
        </ChartCard>
      </div>
      </Fold>
    </div>
  )
}
