import { CategoryBar } from '../../components/dashboard/CategoryBar'
import { CategoryDonut } from '../../components/dashboard/CategoryDonut'
import { ChartCard } from '../../components/dashboard/ChartCard'
import { Fold } from '../../components/dashboard/Fold'
import { DataGrid } from '../../components/dashboard/DataGrid'
import { MonthlyChart } from '../../components/dashboard/MonthlyChart'
import { ReportTable } from '../../components/dashboard/ReportTable'
import { SERIES, count, inr, summarizeRanked, summarizeSeries } from '../../components/dashboard/format'
import { useDashboard } from './DashboardShell'

/** Headcount, movement, cost, and how staff are spread across the cases. */
export function PeopleDashboard() {
  const { series, categories, table, select, active, chip, clear, records } = useDashboard()
  const heads = series('headcount')

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Fold keep={4}>
      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Headcount, joiners and leavers"
        subtitle="People employed each month (line) with those who joined and left (bars)"
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        summary={summarizeSeries(heads, 'headcount', count)}
        records={records('employees', 'Employees')}
      >
        <MonthlyChart
          data={heads}
          bars={[
            { key: 'joiners', label: 'Joined', color: SERIES.joiners, format: 'number' },
            { key: 'leavers', label: 'Left', color: SERIES.leavers, format: 'number' },
          ]}
          lines={[{ key: 'headcount', label: 'Employed', color: SERIES.margin, axis: 'right', format: 'number' }]}
          leftFormat="number"
          rightFormat="number"
          selected={active('month')}
          onSelect={select('month')}
          height={320}
        />
      </ChartCard>

      <ChartCard quiet title="Employment type" subtitle="Active employees now" drill="Click a type" selection={chip('employee_type')} onClear={clear('employee_type')} summary={summarizeRanked(categories('employee_type'), count)}>
        <CategoryDonut data={categories('employee_type')} selected={active('employee_type')} onSelect={select('employee_type')} format={count} centerLabel="People" height={320} />
      </ChartCard>

      <ChartCard
        quiet
        className="lg:col-span-2"
        title="Payroll by month"
        subtitle="Salary booked each month, and the average per person on payroll"
        drill="Click a month"
        selection={chip('month')}
        onClear={clear('month')}
        summary={summarizeSeries(series('payroll'), 'payroll')}
        records={records('payroll', 'Payroll lines')}
      >
        <MonthlyChart
          data={series('payroll')}
          bars={[{ key: 'payroll', label: 'Payroll', color: SERIES.payroll }]}
          lines={[{ key: 'per_head', label: 'Average per person', color: SERIES.margin, axis: 'right', format: 'money' }]}
          rightFormat="money"
          selected={active('month')}
          onSelect={select('month')}
          height={280}
        />
      </ChartCard>

      <ChartCard quiet title="How long people have stayed" subtitle="Active employees by time since joining" summary={summarizeRanked(categories('tenure'), count)}>
        <CategoryBar data={categories('tenure')} format={count} color={SERIES.days} labelWidth={100} height={280} />
      </ChartCard>

      <ChartCard quiet title="Headcount by designation" subtitle="Active employees now" drill="Click a designation" selection={chip('designation')} onClear={clear('designation')} summary={summarizeRanked(categories('headcount_designation'), count)} records={records('active_employees', 'Active employees')}>
        <CategoryBar data={categories('headcount_designation')} selected={active('designation')} onSelect={select('designation')} format={count} labelWidth={130} height={320} />
      </ChartCard>

      <ChartCard quiet title="Payroll by designation" subtitle="Salary booked in this period" drill="Click a designation" selection={chip('designation')} onClear={clear('designation')} summary={summarizeRanked(categories('payroll_designation'))} records={records('payroll', 'Payroll lines')}>
        <CategoryBar data={categories('payroll_designation')} selected={active('designation')} onSelect={select('designation')} format={inr} color={SERIES.payroll} labelWidth={130} height={320} />
      </ChartCard>

      <ChartCard quiet title="Span of control" subtitle="Managers with the most direct reports">
        <DataGrid block={table('managers')} />
      </ChartCard>

      <ChartCard quiet className="lg:col-span-2" title="Designations" subtitle="Headcount, leavers, payroll and average pay for each role. Click a role to filter." drill="Click a designation" selection={chip('designation')} onClear={clear('designation')}>
        <ReportTable block={table('designations')} exportName="orion-designations"
          compact selected={active('designation')} onSelect={select('designation')} defaultSort={{ key: 'payroll', dir: 'desc' }} pageSize={10} maxHeight={380} />
      </ChartCard>

      <ChartCard quiet title="Staff on each case" subtitle="The fifteen largest teams, with the revenue each employee-month earns" drill="Click a case" selection={chip('case')} onClear={clear('case')}>
        <ReportTable block={table('cases')} exportName="orion-staff-by-case"
          compact selected={active('case')} onSelect={select('case')} defaultSort={{ key: 'headcount', dir: 'desc' }} pageSize={15} maxHeight={380} />
      </ChartCard>
      </Fold>
    </div>
  )
}
