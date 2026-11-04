import { CategoryBar } from '../../components/dashboard/CategoryBar'
import { ChartCard } from '../../components/dashboard/ChartCard'
import { Fold } from '../../components/dashboard/Fold'
import { MonthlyChart } from '../../components/dashboard/MonthlyChart'
import { ReportTable } from '../../components/dashboard/ReportTable'
import { SERIES, inr, summarizeRanked } from '../../components/dashboard/format'
import { useDashboard } from './DashboardShell'

/** What a director would want checked: withdrawn and changed bills, GST and salary not yet settled, cases not billed. */
export function ControlsDashboard() {
  const { series, categories, table, select, active, chip, clear, records, go } = useDashboard()
  const trend = series('trend')
  const open = (code: string) => go(`/utility/billing/${encodeURIComponent(code)}`)

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Fold keep={3}>
      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Cancelled and edited bills by month"
        subtitle="Bills withdrawn after being raised, and bills changed after issue. A steady trickle is normal; a spike deserves a question."
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        records={records('cancelled', 'Cancelled bills')}
      >
        <MonthlyChart
          data={trend}
          bars={[
            { key: 'cancelled', label: 'Cancelled', color: SERIES.leavers, format: 'number' },
            { key: 'edited', label: 'Edited', color: SERIES.payroll, format: 'number' },
          ]}
          leftFormat="number"
          selected={active('month')}
          onSelect={select('month')}
          height={300}
        />
      </ChartCard>

      <ChartCard quiet title="GST not marked paid, by age of bill" subtitle="GST charged but not yet shown as paid to the government" summary={summarizeRanked(categories('gst_age'))}>
        <CategoryBar data={categories('gst_age')} format={inr} color={SERIES.gst} labelWidth={52} height={300} emptyMessage="All GST is marked paid." />
      </ChartCard>

      <ChartCard
        quiet
        title="EPFO and ESIC not marked paid, by age of bill"
        subtitle="Charged to clients on bills but not yet shown as paid over to the authority. They are Revenue once charged; once paid over they are a cost and lower the margin."
        summary={summarizeRanked(categories('statutory_age'))}
        records={records('statutory_pending', 'Bills with EPFO or ESIC to pay')}
      >
        <CategoryBar data={categories('statutory_age')} format={inr} color={SERIES.unpaid} labelWidth={52} height={300} emptyMessage="All EPFO and ESIC is marked paid." />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-3"
        title="Salary not yet marked paid, by month"
        subtitle="Payroll lines with the paid flag off. Recent months are expected; older ones need chasing."
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        records={records('payroll_pending', 'Payroll lines not paid')}
      >
        <MonthlyChart
          data={trend}
          bars={[{ key: 'salary_pending', label: 'Salary pending', color: SERIES.unpaid }]}
          selected={active('month')}
          onSelect={select('month')}
          height={220}
        />
      </ChartCard>

      {/* The short lists share a row that adapts to how many have anything in them: one fills it, two halve it. */}
      <div className="grid gap-4 lg:col-span-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 26rem), 1fr))' }}>
        <ChartCard quiet title="Active cases not yet billed" subtitle="Billed last month, nothing yet for the latest month" drill="Click a case" selection={chip('case')} onClear={clear('case')}>
          <ReportTable block={table('unbilled')} exportName="orion-unbilled-cases" selected={active('case')} onSelect={select('case')} pageSize={10} maxHeight={360} />
        </ChartCard>

        <ChartCard quiet title="Cancelled bills" subtitle="Click a bill to open it. Their numbers stay on record." records={records('cancelled', 'Cancelled bills')}>
          <ReportTable block={table('cancelled')} exportName="orion-cancelled-bills" onOpen={open} pageSize={10} maxHeight={360} />
        </ChartCard>

        <ChartCard quiet title="Bills edited after issue" subtitle="Click a bill to open it and see its earlier versions." records={records('edited', 'Bills edited after issue')}>
          <ReportTable block={table('edited')} exportName="orion-edited-bills" onOpen={open} pageSize={10} maxHeight={360} />
        </ChartCard>
      </div>

      <ChartCard quiet className="lg:col-span-2" title="Follow-ups due" subtitle="Active contacts at clients whose next follow-up date has come" records={records('contacts_follow_up', 'Contacts due a follow-up')}>
        <ReportTable block={table('follow_ups')} exportName="orion-contact-follow-ups" defaultSort={{ key: 'late', dir: 'desc' }} pageSize={10} maxHeight={360} />
      </ChartCard>

      <ChartCard quiet title="Clients with no active contact" subtitle="Active clients where nobody is on record to call" records={records('contacts', 'Client contacts')}>
        <ReportTable block={table('no_contact')} exportName="orion-clients-without-contact" pageSize={10} maxHeight={360} />
      </ChartCard>

      <ChartCard quiet className="lg:col-span-3" title="GST to mark as paid" subtitle="Issued bills whose GST is not marked paid" records={records('gst_pending', 'Bills with GST to mark paid')}>
        <ReportTable block={table('gst')} exportName="orion-gst-pending" onOpen={open} defaultSort={{ key: 'gst', dir: 'desc' }} pageSize={10} maxHeight={360} />
      </ChartCard>

      <ChartCard quiet className="lg:col-span-3" title="EPFO and ESIC to mark as paid" subtitle="Issued bills with EPFO or ESIC not yet paid over. Open a bill to record the payment." records={records('statutory_pending', 'Bills with EPFO or ESIC to pay')}>
        <ReportTable block={table('statutory')} exportName="orion-epfo-esic-pending" onOpen={open} defaultSort={{ key: 'epf', dir: 'desc' }} pageSize={10} maxHeight={360} />
      </ChartCard>
      </Fold>
    </div>
  )
}
