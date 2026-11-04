import { CategoryBar } from '../../components/dashboard/CategoryBar'
import { CategoryDonut } from '../../components/dashboard/CategoryDonut'
import { ChartCard } from '../../components/dashboard/ChartCard'
import { Fold } from '../../components/dashboard/Fold'
import { MonthlyChart } from '../../components/dashboard/MonthlyChart'
import { ReportTable } from '../../components/dashboard/ReportTable'
import { SERIES, inr, summarizeRanked, summarizeSeries } from '../../components/dashboard/format'
import { useDashboard } from './DashboardShell'

/** Cash in, money still out, how old it is, and who is slow to pay. */
export function CollectionsDashboard() {
  const { series, categories, table, select, active, chip, clear, records, go } = useDashboard()
  const cash = series('cash')
  const days = (value: number) => `${value.toFixed(0)} d`

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Fold keep={3}>
      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Billed and collected by month"
        subtitle="Invoices raised against the cash that reached the bank and the TDS clients held back, and the share of billing that was settled by the two. The last month may be part-way."
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
            { key: 'collected', label: 'Cash collected', color: SERIES.committed },
            { key: 'tds', label: 'TDS held back', color: SERIES.margin },
          ]}
          lines={[{ key: 'rate', label: 'Settled % of billed', color: SERIES.margin, axis: 'right', format: 'percent' }]}
          selected={active('month')}
          onSelect={select('month')}
          height={320}
        />
      </ChartCard>

      <ChartCard
        quiet
        title="Money owed, by age"
        subtitle="Unpaid balance today, by how long ago the bill was raised"
        drill="Click an age"
        selection={chip('bucket')}
        onClear={clear('bucket')}
        summary={summarizeRanked(categories('ageing'))}
        records={records('receivables', 'Unpaid bills')}
      >
        <CategoryBar data={categories('ageing')} selected={active('bucket')} onSelect={select('bucket')} color={SERIES.unpaid} format={inr} labelWidth={52} height={320} emptyMessage="Nothing is owed." />
      </ChartCard>

      <ChartCard
        quiet
        title="Who owes the most"
        subtitle="Ten largest unpaid balances"
        drill="Click a client"
        selection={chip('client')}
        onClear={clear('client')}
        summary={summarizeRanked(categories('owed_clients'))}
        records={records('receivables', 'Unpaid bills')}
      >
        <CategoryBar data={categories('owed_clients')} selected={active('client')} onSelect={select('client')} color={SERIES.unpaid} format={inr} labelWidth={150} height={340} />
      </ChartCard>

      <ChartCard
        quiet
        title="Payment status of what was billed"
        subtitle="By value, for the bills in this period"
        drill="Click a status"
        selection={chip('pay_status')}
        onClear={clear('pay_status')}
        summary={summarizeRanked(categories('pay_status'))}
      >
        <CategoryDonut data={categories('pay_status')} selected={active('pay_status')} onSelect={select('pay_status')} format={inr} centerLabel="Billed" height={300} colors={[SERIES.committed, SERIES.prospective, SERIES.unpaid]} />
      </ChartCard>

      <ChartCard
        quiet
        title="How long clients take to pay"
        subtitle="Average days from bill to last payment, by client type, on fully paid bills"
        drill="Click a type"
        selection={chip('client_type')}
        onClear={clear('client_type')}
        summary={summarizeRanked(categories('days_by_type'), days)}
      >
        <CategoryBar data={categories('days_by_type')} selected={active('client_type')} onSelect={select('client_type')} format={days} color={SERIES.days} labelWidth={80} height={240} />
      </ChartCard>

      <ChartCard quiet title="Owed, by client type" drill="Click a type" selection={chip('client_type')} onClear={clear('client_type')} summary={summarizeRanked(categories('owed_type'))}>
        <CategoryBar data={categories('owed_type')} selected={active('client_type')} onSelect={select('client_type')} format={inr} color={SERIES.unpaid} labelWidth={80} height={220} />
      </ChartCard>

      <ChartCard quiet title="Owed, by business domain" drill="Click a domain" selection={chip('business_domain')} onClear={clear('business_domain')} summary={summarizeRanked(categories('owed_domain'))}>
        <CategoryBar data={categories('owed_domain')} selected={active('business_domain')} onSelect={select('business_domain')} format={inr} color={SERIES.unpaid} labelWidth={130} height={220} />
      </ChartCard>

      <ChartCard quiet title="GST on these bills" subtitle="Whether the GST has been marked as paid to the government" summary={summarizeRanked(categories('gst'))}>
        <CategoryDonut data={categories('gst')} format={inr} centerLabel="GST" height={220} colors={[SERIES.committed, SERIES.unpaid]} />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Clients and what they owe"
        subtitle="Unpaid balance, how much is over 90 days, the oldest bill, and how quickly the client usually pays. Click a client to focus the page."
        drill="Click a client"
        selection={chip('client')}
        onClear={clear('client')}
        records={records('receivables', 'Unpaid bills')}
      >
        <ReportTable
          block={table('owed_clients')}
          exportName="orion-clients-owing"
          compact
          selected={active('client')}
          onSelect={select('client')}
          defaultSort={{ key: 'owed', dir: 'desc' }}
          pageSize={10}
          maxHeight={400}
        />
      </ChartCard>

      <ChartCard quiet title="Latest payments" subtitle="The fifteen most recent receipts" records={records('receipts', 'Payments received')}>
        <ReportTable block={table('receipts')} exportName="orion-latest-receipts" pageSize={15} maxHeight={400} />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-3"
        title="Unpaid bills, oldest first"
        subtitle="Every bill with a balance. Click a bill to open it and record a payment or send a reminder."
        records={records('receivables', 'Unpaid bills')}
      >
        <ReportTable
          block={table('overdue')}
          exportName="orion-unpaid-bills"
          onOpen={(code) => go(`/utility/billing/${encodeURIComponent(code)}`)}
          defaultSort={{ key: 'age', dir: 'desc' }}
          pageSize={10}
          maxHeight={460}
        />
      </ChartCard>
      </Fold>
    </div>
  )
}
