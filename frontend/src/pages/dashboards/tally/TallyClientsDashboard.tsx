import { useState } from 'react'
import { CategoryBar } from '../../../components/dashboard/CategoryBar'
import { ChartCard } from '../../../components/dashboard/ChartCard'
import { ReportTable } from '../../../components/dashboard/ReportTable'
import { SERIES, inr, summarizeRanked } from '../../../components/dashboard/format'
import { useTallyDashboard } from '../../TallyDashboardPage'

type Detail = 'billed' | 'debtors'

const DETAIL_TABS: { id: Detail; label: string }[] = [
  { id: 'billed', label: 'Billed in this selection' },
  { id: 'debtors', label: 'Debtor balances (snapshot)' },
]

/** Who are we billing, how concentrated is it, and who owes us? */
export function TallyClientsDashboard() {
  const { categories, table, select, active, chip, clear } = useTallyDashboard()
  const [detail, setDetail] = useState<Detail>('billed')
  const clients = categories('top_clients').slice(0, 10)
  const debtors = categories('debtors').slice(0, 10)
  const centres = categories('by_cost_centre')

  return (
    <div className="grid gap-4 lg:grid-cols-3">
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
          height={330}
        />
      </ChartCard>

      <ChartCard
        quiet
        title="Largest debtor balances"
        subtitle="Closing balance at the last load, shown as an amount owed. Not affected by the period."
        drill="Click a debtor"
        selection={chip('client')}
        onClear={clear('client')}
        summary={summarizeRanked(debtors)}
      >
        <CategoryBar
          data={debtors}
          selected={active('client')}
          onSelect={select('client')}
          color={SERIES.payroll}
          format={inr}
          labelWidth={110}
          height={330}
          emptyMessage="No Sundry Debtor ledgers in the warehouse."
        />
      </ChartCard>

      {centres.length > 0 && (
        <ChartCard
          quiet
          className="lg:col-span-3"
          title="Revenue by cost centre"
          subtitle="Where Tally split the voucher. Only vouchers with a cost centre are counted here."
          drill="Click a centre"
          selection={chip('cost_centre')}
          onClear={clear('cost_centre')}
          summary={summarizeRanked(centres)}
        >
          <CategoryBar
            data={centres}
            selected={active('cost_centre')}
            onSelect={select('cost_centre')}
            color={SERIES.km}
            format={inr}
            labelWidth={150}
            height={Math.max(120, centres.length * 26 + 20)}
          />
        </ChartCard>
      )}

      <ChartCard
        quiet
        className="lg:col-span-3"
        title={detail === 'billed' ? 'Clients billed' : 'Debtor ledgers'}
        subtitle={
          detail === 'billed'
            ? 'Documents, billed value, revenue and share of revenue per client. Click a row to filter.'
            : 'Closing balance per Sundry Debtor at the last load, next to what was billed in the selected period.'
        }
        drill="Click a client"
        selection={chip('client')}
        onClear={clear('client')}
        actions={
          <div role="tablist" aria-label="Table view" className="flex rounded-lg bg-muted p-0.5">
            {DETAIL_TABS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={detail === item.id}
                onClick={() => setDetail(item.id)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  detail === item.id
                    ? 'bg-surface text-[color:var(--color-text)] shadow-sm'
                    : 'text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        }
      >
        {detail === 'billed' ? (
          <ReportTable
            key="billed"
            block={table('clients')}
            exportName="tally-clients-billed"
            selected={active('client')}
            onSelect={select('client')}
            searchLabel="Search clients"
            hidden={['gst']}
            defaultSort={{ key: 'revenue', dir: 'desc' }}
            emptyMessage="No billed clients in this selection."
          />
        ) : (
          <ReportTable
            key="debtors"
            block={table('debtors')}
            exportName="tally-debtor-ledgers"
            selected={active('client')}
            onSelect={select('client')}
            searchLabel="Search debtors"
            emptyMessage="No Sundry Debtor ledgers in the warehouse."
          />
        )}
      </ChartCard>
    </div>
  )
}
