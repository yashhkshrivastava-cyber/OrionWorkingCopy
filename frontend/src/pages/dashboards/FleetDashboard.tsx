import { CategoryBar } from '../../components/dashboard/CategoryBar'
import { ChartCard } from '../../components/dashboard/ChartCard'
import { Fold } from '../../components/dashboard/Fold'
import { MonthlyChart } from '../../components/dashboard/MonthlyChart'
import { ReportTable } from '../../components/dashboard/ReportTable'
import { SERIES, count, inr, summarizeRanked, summarizeSeries } from '../../components/dashboard/format'
import { useDashboard } from './DashboardShell'

/** Distance driven, what it costs, which cars and drivers carry it, and whether cases keep to their allowance. */
export function FleetDashboard() {
  const { series, categories, table, select, active, chip, clear, records } = useDashboard()
  const trend = series('trend')

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Fold keep={5}>
      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Kilometres and cost by month"
        subtitle="Distance driven (bars) and what it cost (line)"
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        summary={summarizeSeries(trend, 'km', count)}
        records={records('fleet', 'Car logs')}
      >
        <MonthlyChart
          data={trend}
          bars={[{ key: 'km', label: 'Kilometres', color: SERIES.km, format: 'number' }]}
          lines={[{ key: 'cost', label: 'Fleet cost', color: SERIES.cost, axis: 'right', format: 'money' }]}
          leftFormat="number"
          rightFormat="money"
          selected={active('month')}
          onSelect={select('month')}
          height={320}
        />
      </ChartCard>

      <ChartCard quiet title="Cost of a kilometre" subtitle="Fleet cost divided by distance, by month">
        <MonthlyChart data={trend} lines={[{ key: 'per_km', label: '₹ per km', color: SERIES.rate, format: 'money' }]} selected={active('month')} onSelect={select('month')} height={320} />
      </ChartCard>

      <ChartCard quiet title="Kilometres by car model" drill="Click a model" selection={chip('car_model')} onClear={clear('car_model')} summary={summarizeRanked(categories('by_model'), count)} records={records('fleet', 'Car logs')}>
        <CategoryBar data={categories('by_model')} selected={active('car_model')} onSelect={select('car_model')} format={count} labelWidth={140} height={280} />
      </ChartCard>

      <ChartCard quiet title="Busiest drivers" subtitle="Kilometres driven, top ten" drill="Click a driver" selection={chip('driver')} onClear={clear('driver')} summary={summarizeRanked(categories('by_driver'), count)}>
        <CategoryBar data={categories('by_driver')} selected={active('driver')} onSelect={select('driver')} format={count} color={SERIES.days} labelWidth={120} height={280} />
      </ChartCard>

      <ChartCard quiet title="Where the fleet cost sits" subtitle="Cost by case, top ten" drill="Click a case" selection={chip('case')} onClear={clear('case')} summary={summarizeRanked(categories('cost_by_case'))}>
        <CategoryBar data={categories('cost_by_case')} selected={active('case')} onSelect={select('case')} format={inr} color={SERIES.cost} labelWidth={150} height={280} />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Km allowance by case"
        subtitle="Average monthly distance against the case's monthly allowance. Over 100% means the case drives past what it is allowed."
        drill="Click a case"
        selection={chip('case')}
        onClear={clear('case')}
      >
        <ReportTable block={table('allowance')} exportName="orion-km-allowance" selected={active('case')} onSelect={select('case')} pageSize={10} maxHeight={380} />
      </ChartCard>

      <ChartCard quiet title="Every car" subtitle="Distance, days on the road and cost for each car" records={records('fleet', 'Car logs')}>
        <ReportTable block={table('cars')} exportName="orion-cars"
          compact defaultSort={{ key: 'km', dir: 'desc' }} pageSize={10} maxHeight={380} />
      </ChartCard>
      </Fold>
    </div>
  )
}
