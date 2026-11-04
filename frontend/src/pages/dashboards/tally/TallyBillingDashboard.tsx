import { useMemo } from 'react'
import { CategoryBar } from '../../../components/dashboard/CategoryBar'
import { ChartCard } from '../../../components/dashboard/ChartCard'
import { MonthlyChart } from '../../../components/dashboard/MonthlyChart'
import { ReportTable } from '../../../components/dashboard/ReportTable'
import { SERIES, inr, summarizeRanked, summarizeSeries } from '../../../components/dashboard/format'
import type { TableBlock } from '../../../types'
import { useTallyDashboard } from '../../TallyDashboardPage'

const num = (value: unknown) => Number(value) || 0

/** How much paper went out, how big was it, and what does each month add up to? */
export function TallyBillingDashboard() {
  const { series, categories, select, active, chip, clear } = useTallyDashboard()
  const trend = series('trend')
  const docs = series('documents')
  const companies = categories('by_company')
  const years = categories('by_fy')

  // Both series cover the same months, so they join on the month code.
  const months = useMemo(() => {
    const byCode = new Map(trend.map((point) => [point.code, point]))
    return docs.map((doc) => {
      const base = byCode.get(doc.code)
      const salesCount = num(doc.sales_count)
      return {
        code: doc.code,
        label: doc.label,
        documents: num(base?.invoices),
        sales: num(doc.sales),
        credit_notes: -num(doc.credit_notes),
        debit_notes: num(doc.debit_notes),
        net: num(doc.net),
        revenue: num(base?.revenue),
        gst: num(base?.gst),
        // Sales invoices only: credit and debit notes are not "invoices" for sizing purposes.
        avg_sales: salesCount ? num(doc.sales) / salesCount : 0,
      }
    })
  }, [trend, docs])

  const table: TableBlock = useMemo(
    () => ({
      filter_key: 'month',
      columns: [
        { key: 'label', label: 'Month', format: 'text', align: 'left' },
        { key: 'documents', label: 'Documents', format: 'number', align: 'right' },
        { key: 'sales', label: 'Sales', format: 'money', align: 'right' },
        { key: 'credit_notes', label: 'Credit notes', format: 'money', align: 'right' },
        { key: 'debit_notes', label: 'Debit notes', format: 'money', align: 'right' },
        { key: 'net', label: 'Net billed', format: 'money', align: 'right' },
        { key: 'revenue', label: 'Revenue ex GST', format: 'money', align: 'right' },
        { key: 'gst', label: 'GST', format: 'money', align: 'right' },
      ],
      rows: [...months].reverse(),
      truncated: false,
      totals: months.length
        ? {
            documents: months.reduce((sum, row) => sum + row.documents, 0),
            sales: months.reduce((sum, row) => sum + row.sales, 0),
            credit_notes: months.reduce((sum, row) => sum + row.credit_notes, 0),
            debit_notes: months.reduce((sum, row) => sum + row.debit_notes, 0),
            net: months.reduce((sum, row) => sum + row.net, 0),
            revenue: months.reduce((sum, row) => sum + row.revenue, 0),
            gst: months.reduce((sum, row) => sum + row.gst, 0),
          }
        : null,
    }),
    [months],
  )

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Documents and average sales invoice"
        subtitle="Bars: every document issued (sales, credit and debit notes). Line: average value of a sales invoice."
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        summary={summarizeSeries(months, 'documents', (value) => `${Math.round(value)} documents`)}
      >
        <MonthlyChart
          data={months}
          bars={[{ key: 'documents', label: 'Documents', color: SERIES.base, format: 'number' }]}
          lines={[
            { key: 'avg_sales', label: 'Average sales invoice', color: SERIES.payroll, axis: 'right', format: 'money' },
          ]}
          leftFormat="number"
          rightFormat="money"
          selected={active('month')}
          onSelect={select('month')}
          height={280}
        />
      </ChartCard>

      <ChartCard
        quiet
        title="Revenue by financial year"
        subtitle="April to March, ex GST"
        drill="Click a year"
        selection={chip('fy')}
        onClear={clear('fy')}
        summary={summarizeRanked(years)}
      >
        <CategoryBar
          data={years}
          selected={active('fy')}
          onSelect={select('fy')}
          color={SERIES.base}
          format={inr}
          labelWidth={84}
          height={150}
        />
        {companies.length > 1 && (
          <div className="mt-2 border-t border-[color:var(--color-border)] pt-2">
            <p className="px-3 pb-1 text-xs font-medium text-[color:var(--color-text-muted)]">By company</p>
            <CategoryBar
              data={companies}
              selected={active('company')}
              onSelect={select('company')}
              color={SERIES.base}
              format={inr}
              labelWidth={120}
              height={140}
            />
          </div>
        )}
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-3"
        title="Monthly billing detail"
        subtitle="Every month in the selected window. Net billed = sales + debit notes − credit notes."
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
      >
        <ReportTable
          block={table}
          exportName="tally-monthly-billing"
          selected={active('month')}
          onSelect={select('month')}
          searchLabel="Search months"
          hidden={['debit_notes']}
          negativeTone
          pageSize={12}
          emptyMessage="No billed months in this selection."
        />
      </ChartCard>
    </div>
  )
}
