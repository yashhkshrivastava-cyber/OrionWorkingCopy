import { CategoryBar } from '../../components/dashboard/CategoryBar'
import { CategoryDonut } from '../../components/dashboard/CategoryDonut'
import { ChartCard } from '../../components/dashboard/ChartCard'
import { Fold } from '../../components/dashboard/Fold'
import { MonthlyChart } from '../../components/dashboard/MonthlyChart'
import { ReportTable } from '../../components/dashboard/ReportTable'
import { StageFunnel } from '../../components/dashboard/StageFunnel'
import { SERIES, count, inr, summarizeRanked, summarizeSeries } from '../../components/dashboard/format'
import { useDashboard } from './DashboardShell'

/** Tenders by stage, how often they are won, why they are lost, and what the wins now bill. */
export function PipelineDashboard() {
  const { series, categories, table, select, active, chip, clear, records } = useDashboard()
  const trend = series('trend')

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Fold keep={5}>
      <ChartCard
        quiet
        title="Opportunities by stage"
        subtitle="Click a stage to filter the page"
        drill="Click a stage"
        selection={chip('stage')}
        onClear={clear('stage')}
        summary={summarizeRanked(categories('funnel'), count)}
        records={records('opportunities', 'Opportunities')}
      >
        <StageFunnel data={categories('funnel')} selected={active('stage')} onSelect={select('stage')} caption="opportunities" />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Opportunities opened each month"
        subtitle="How many were opened, and how many of those were later won or lost"
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        summary={summarizeSeries(trend, 'opps', count)}
        records={records('opportunities', 'Opportunities')}
      >
        <MonthlyChart
          data={trend}
          bars={[
            { key: 'won', label: 'Won', color: SERIES.joiners, stackId: 'o', format: 'number' },
            { key: 'lost', label: 'Lost or disqualified', color: SERIES.leavers, stackId: 'o', format: 'number' },
          ]}
          lines={[{ key: 'opps', label: 'Opened', color: SERIES.margin, format: 'number' }]}
          leftFormat="number"
          selected={active('month')}
          onSelect={select('month')}
          height={300}
        />
      </ChartCard>

      <ChartCard quiet title="Why tenders are lost" subtitle="Reasons recorded on lost and disqualified opportunities" summary={summarizeRanked(categories('loss_reasons'), count)}>
        <CategoryBar data={categories('loss_reasons')} format={count} color={SERIES.leavers} labelWidth={170} height={280} emptyMessage="No reasons recorded." />
      </ChartCard>

      <ChartCard quiet title="Opportunities by state" drill="Click a state" selection={chip('state')} onClear={clear('state')} summary={summarizeRanked(categories('by_state'), count)}>
        <CategoryBar data={categories('by_state')} selected={active('state')} onSelect={select('state')} format={count} color={SERIES.days} labelWidth={110} height={280} />
      </ChartCard>

      <ChartCard quiet title="By tender type" subtitle="State, national or private" drill="Click a type" selection={chip('opp_type')} onClear={clear('opp_type')} summary={summarizeRanked(categories('by_type'), count)}>
        <CategoryDonut data={categories('by_type')} selected={active('opp_type')} onSelect={select('opp_type')} format={count} centerLabel="Tenders" height={280} />
      </ChartCard>

      <ChartCard quiet className="lg:col-span-2" title="Win rate by financial year" subtitle="Opportunities opened, won and lost, and how long they took to decide" drill="Click a year" selection={chip('fy')} onClear={clear('fy')}>
        <ReportTable block={table('fy')} exportName="orion-win-rate-by-year" selected={active('fy')} onSelect={select('fy')} defaultSort={{ key: 'fy', dir: 'asc' }} pageSize={10} maxHeight={300} />
      </ChartCard>

      <ChartCard quiet title="Open opportunities" subtitle="Oldest first. Stale means no stage change for over 90 days." records={records('open_opps', 'Open opportunities')}>
        <ReportTable block={table('open')} exportName="orion-open-opportunities" pageSize={10} maxHeight={300} />
      </ChartCard>

      <ChartCard quiet title="EMD by status" subtitle="Earnest money deposited in the period, by where it stands" summary={summarizeRanked(categories('emd_by_status'), inr)} records={records('emds', 'EMDs')}>
        <CategoryBar data={categories('emd_by_status')} format={inr} color={SERIES.unpaid} labelWidth={170} height={280} emptyMessage="No EMDs deposited." />
      </ChartCard>

      <ChartCard quiet className="lg:col-span-2" title="EMD still to come back" subtitle="Earliest refund first. A bank guarantee or FDR that is about to lapse is flagged too." records={records('emds_open', 'EMDs still to come back')}>
        <ReportTable block={table('emd')} exportName="orion-emd-to-come-back" pageSize={10} maxHeight={300} />
      </ChartCard>

      <ChartCard quiet className="lg:col-span-3" title="What the wins now bill" subtitle="Won opportunities that became cases, with the revenue each has produced so far">
        <ReportTable block={table('won')} exportName="orion-won-opportunities"
          compact defaultSort={{ key: 'revenue', dir: 'desc' }} pageSize={10} maxHeight={420} />
      </ChartCard>
      </Fold>
    </div>
  )
}
