import { Route, Navigate } from 'react-router-dom'
import { lazyPage } from './lazyPage'
import { AdminRoute, BankRoute, DashboardRoute, DataRoute, UtilityRoute, EtlRoute, LetterheadRoute, DocumentsRoute, TendersRoute, AttendanceRoute, SqlRoute } from './components/ProtectedRoute'

const SqlEditorPage = lazyPage(() => import('./pages/sql/SqlEditorPage'), 'SqlEditorPage')
const AdminPage = lazyPage(() => import('./pages/AdminPage'), 'AdminPage')
const DashboardManagementPage = lazyPage(() => import('./pages/DashboardManagementPage'), 'DashboardManagementPage')
const TallyDashboardPage = lazyPage(() => import('./pages/TallyDashboardPage'), 'TallyDashboardPage')
const TallyOverviewDashboard = lazyPage(() => import('./pages/dashboards/tally/TallyOverviewDashboard'), 'TallyOverviewDashboard')
const TallyBillingDashboard = lazyPage(() => import('./pages/dashboards/tally/TallyBillingDashboard'), 'TallyBillingDashboard')
const TallyNotesDashboard = lazyPage(() => import('./pages/dashboards/tally/TallyNotesDashboard'), 'TallyNotesDashboard')
const TallyIncomeDashboard = lazyPage(() => import('./pages/dashboards/tally/TallyIncomeDashboard'), 'TallyIncomeDashboard')
const TallyClientsDashboard = lazyPage(() => import('./pages/dashboards/tally/TallyClientsDashboard'), 'TallyClientsDashboard')
const TallyBooksDashboard = lazyPage(() => import('./pages/dashboards/tally/TallyBooksDashboard'), 'TallyBooksDashboard')
const DataManagementPage = lazyPage(() => import('./pages/DataManagementPage'), 'DataManagementPage')
const OrionDataPage = lazyPage(() => import('./pages/OrionDataPage'), 'OrionDataPage')
const TallyDataPage = lazyPage(() => import('./pages/TallyDataPage'), 'TallyDataPage')
const MessagesPage = lazyPage(() => import('./pages/MessagesPage'), 'MessagesPage')
const ClientsPage = lazyPage(() => import('./pages/clients/ClientsPage'), 'ClientsPage')
const ClientPage = lazyPage(() => import('./pages/clients/ClientPage'), 'ClientPage')
const CasesPage = lazyPage(() => import('./pages/clients/CasesPage'), 'CasesPage')
const CasePage = lazyPage(() => import('./pages/clients/CasePage'), 'CasePage')
const EmployeesPage = lazyPage(() => import('./pages/clients/EmployeesPage'), 'EmployeesPage')
const EmployeePage = lazyPage(() => import('./pages/clients/EmployeePage'), 'EmployeePage')
const UserPage = lazyPage(() => import('./pages/clients/UserPage'), 'UserPage')
const OperationalDataPage = lazyPage(() => import('./pages/OperationalDataPage'), 'OperationalDataPage')
const WarehousePage = lazyPage(() => import('./pages/WarehousePage'), 'WarehousePage')
const TallyOdsPage = lazyPage(() => import('./pages/TallyOdsPage'), 'TallyOdsPage')
const TallyDwPage = lazyPage(() => import('./pages/TallyDwPage'), 'TallyDwPage')
const UtilityPage = lazyPage(() => import('./pages/utility/UtilityPage'), 'UtilityPage')
const BillingPage = lazyPage(() => import('./pages/utility/BillingPage'), 'BillingPage')
const BillEditorPage = lazyPage(() => import('./pages/utility/BillEditorPage'), 'BillEditorPage')
const BillFindPage = lazyPage(() => import('./pages/utility/BillFindPage'), 'BillFindPage')
const BillViewPage = lazyPage(() => import('./pages/utility/BillViewPage'), 'BillViewPage')
const DueToBillPage = lazyPage(() => import('./pages/utility/DueToBillPage'), 'DueToBillPage')
const ReceivablesPage = lazyPage(() => import('./pages/utility/ReceivablesPage'), 'ReceivablesPage')
const TdsPage = lazyPage(() => import('./pages/utility/TdsPage'), 'TdsPage')
const GstPage = lazyPage(() => import('./pages/utility/GstPage'), 'GstPage')
const StatutoryPage = lazyPage(() => import('./pages/utility/StatutoryPage'), 'StatutoryPage')
const CreditNotesPage = lazyPage(() => import('./pages/utility/CreditNotesPage'), 'CreditNotesPage')
const LetterheadPage = lazyPage(() => import('./pages/letterhead/LetterheadPage'), 'LetterheadPage')
const PdfToolsPage = lazyPage(() => import('./pages/pdftools/PdfToolsPage'), 'PdfToolsPage')
const PdfToolsHome = lazyPage(() => import('./pages/pdftools/PdfToolsHome'), 'PdfToolsHome')
const PdfToolPage = lazyPage(() => import('./pages/pdftools/PdfToolPage'), 'PdfToolPage')
const LettersPage = lazyPage(() => import('./pages/letterhead/LettersPage'), 'LettersPage')
const LetterEditorPage = lazyPage(() => import('./pages/letterhead/LetterEditorPage'), 'LetterEditorPage')
const StampPdfPage = lazyPage(() => import('./pages/letterhead/StampPdfPage'), 'StampPdfPage')
const LetterheadDesignPage = lazyPage(() => import('./pages/letterhead/LetterheadDesignPage'), 'LetterheadDesignPage')
const DocumentCenterPage = lazyPage(() => import('./pages/documents/DocumentCenterPage'), 'DocumentCenterPage')
const BankPage = lazyPage(() => import('./pages/bank/BankPage'), 'BankPage')
const BankOverviewPage = lazyPage(() => import('./pages/bank/BankOverviewPage'), 'BankOverviewPage')
const BankLedgerPage = lazyPage(() => import('./pages/bank/BankLedgerPage'), 'BankLedgerPage')
const BankReconcilePage = lazyPage(() => import('./pages/bank/BankReconcilePage'), 'BankReconcilePage')
const BankAccountPage = lazyPage(() => import('./pages/bank/BankAccountPage'), 'BankAccountPage')
const BankPayablesPage = lazyPage(() => import('./pages/bank/BankPayablesPage'), 'BankPayablesPage')
const BankPayrollPage = lazyPage(() => import('./pages/bank/BankPayrollPage'), 'BankPayrollPage')
const AttendancePage = lazyPage(() => import('./pages/attendance/AttendancePage'), 'AttendancePage')
const AttendanceSheetPage = lazyPage(() => import('./pages/attendance/AttendanceSheetPage'), 'AttendanceSheetPage')
const TasksPage = lazyPage(() => import('./pages/tasks/TasksPage'), 'TasksPage')
const MyWorkPage = lazyPage(() => import('./pages/tasks/MyWorkPage'), 'MyWorkPage')
const TodoPage = lazyPage(() => import('./pages/tasks/TodoPage'), 'TodoPage')
const ProjectsPage = lazyPage(() => import('./pages/tasks/ProjectsPage'), 'ProjectsPage')
const ProjectPage = lazyPage(() => import('./pages/tasks/ProjectPage'), 'ProjectPage')
const TaskReportsPage = lazyPage(() => import('./pages/tasks/ReportsPage'), 'ReportsPage')
const TaskInboxPage = lazyPage(() => import('./pages/tasks/InboxPage'), 'InboxPage')
const EtlPage = lazyPage(() => import('./pages/EtlPage'), 'EtlPage')
const GemTendersPage = lazyPage(() => import('./pages/tenders/TendersPage'), 'GemTendersPage')
const MpTendersPage = lazyPage(() => import('./pages/tenders/TendersPage'), 'MpTendersPage')
const DashboardShell = lazyPage(() => import('./pages/dashboards/DashboardShell'), 'DashboardShell')
const CollectionsDashboard = lazyPage(() => import('./pages/dashboards/CollectionsDashboard'), 'CollectionsDashboard')
const ControlsDashboard = lazyPage(() => import('./pages/dashboards/ControlsDashboard'), 'ControlsDashboard')
const FleetDashboard = lazyPage(() => import('./pages/dashboards/FleetDashboard'), 'FleetDashboard')
const OverviewDashboard = lazyPage(() => import('./pages/dashboards/OverviewDashboard'), 'OverviewDashboard')
const PeopleDashboard = lazyPage(() => import('./pages/dashboards/PeopleDashboard'), 'PeopleDashboard')
const PipelineDashboard = lazyPage(() => import('./pages/dashboards/PipelineDashboard'), 'PipelineDashboard')
const ProfitabilityDashboard = lazyPage(() => import('./pages/dashboards/ProfitabilityDashboard'), 'ProfitabilityDashboard')
const RevenueDashboard = lazyPage(() => import('./pages/dashboards/RevenueDashboard'), 'RevenueDashboard')
const OrionForecastPage = lazyPage(() => import('./pages/dashboards/ForecastPage'), 'OrionForecastPage')
const TallyForecastPage = lazyPage(() => import('./pages/dashboards/ForecastPage'), 'TallyForecastPage')
const CashDashboard = lazyPage(() => import('./pages/dashboards/CashDashboard'), 'CashDashboard')

export function dashboardRouteTree() {
  return (
    <Route element={<DashboardRoute />}>
      <Route path="/dashboard" element={<DashboardManagementPage />} />
      <Route path="/dashboard/orion/forecast" element={<OrionForecastPage />} />
      <Route path="/dashboard/tally/forecast" element={<TallyForecastPage />} />
      <Route path="/dashboard/orion" element={<DashboardShell />}>
        <Route index element={<OverviewDashboard />} />
        <Route path="revenue" element={<RevenueDashboard />} />
        <Route path="collections" element={<CollectionsDashboard />} />
        <Route path="profitability" element={<ProfitabilityDashboard />} />
        <Route path="people" element={<PeopleDashboard />} />
        <Route path="pipeline" element={<PipelineDashboard />} />
        <Route path="fleet" element={<FleetDashboard />} />
        <Route path="controls" element={<ControlsDashboard />} />
        <Route path="cash" element={<CashDashboard />} />
        <Route path="delivery" element={<Navigate to="/dashboard/orion/profitability" replace />} />
      </Route>
      <Route path="/dashboard/tally" element={<TallyDashboardPage />}>
        <Route index element={<TallyOverviewDashboard />} />
        <Route path="billing" element={<TallyBillingDashboard />} />
        <Route path="credit-notes" element={<TallyNotesDashboard />} />
        <Route path="income" element={<TallyIncomeDashboard />} />
        <Route path="clients" element={<TallyClientsDashboard />} />
        <Route path="books" element={<TallyBooksDashboard />} />
      </Route>
      <Route path="/dashboard/revenue" element={<Navigate to="/dashboard/orion/revenue" replace />} />
      <Route path="/dashboard/delivery" element={<Navigate to="/dashboard/orion/profitability" replace />} />
      <Route path="/dashboard/people" element={<Navigate to="/dashboard/orion/people" replace />} />
      <Route path="/dashboard/pipeline" element={<Navigate to="/dashboard/orion/pipeline" replace />} />
      <Route path="/dashboard/fleet" element={<Navigate to="/dashboard/orion/fleet" replace />} />
    </Route>
  )
}

export function dataRouteTree() {
  return (
    <Route element={<DataRoute />}>
      <Route path="/data" element={<DataManagementPage />} />
      <Route path="/data/orion" element={<OrionDataPage />} />
      <Route path="/data/operational" element={<OperationalDataPage />} />
      <Route path="/data/clients" element={<ClientsPage />} />
      <Route path="/data/clients/:code" element={<ClientPage />} />
      <Route path="/data/cases" element={<CasesPage />} />
      <Route path="/data/cases/:code" element={<CasePage />} />
      <Route path="/data/employees" element={<EmployeesPage />} />
      <Route path="/data/employees/:code" element={<EmployeePage />} />
      <Route path="/data/warehouse" element={<WarehousePage />} />
      <Route path="/data/tally" element={<TallyDataPage />} />
      <Route path="/data/tally/working" element={<TallyOdsPage />} />
      <Route path="/data/tally/warehouse" element={<TallyDwPage />} />
    </Route>
  )
}

export function utilityRouteTree() {
  return (
    <Route element={<UtilityRoute />}>
      <Route path="/utility" element={<UtilityPage />}>
        <Route index element={<Navigate to="billing" replace />} />
        <Route path="billing" element={<BillingPage />} />
        <Route path="billing/new" element={<BillEditorPage />} />
        <Route path="billing/find" element={<BillFindPage />} />
        <Route path="billing/:id" element={<BillViewPage />} />
        <Route path="billing/:id/edit" element={<BillEditorPage />} />
        <Route path="receivables" element={<ReceivablesPage />} />
        <Route path="tds" element={<TdsPage />} />
        <Route path="gst" element={<GstPage />} />
        <Route path="statutory" element={<StatutoryPage />} />
        <Route path="credit-notes" element={<CreditNotesPage />} />
        <Route path="due" element={<DueToBillPage />} />
      </Route>
    </Route>
  )
}

export function letterheadRouteTree() {
  return (
    <Route element={<LetterheadRoute />}>
      <Route path="/letterhead" element={<LetterheadPage />}>
        <Route index element={<Navigate to="letters" replace />} />
        <Route path="letters" element={<LettersPage />} />
        <Route path="letters/new" element={<LetterEditorPage />} />
        <Route path="letters/:id" element={<LetterEditorPage />} />
        <Route path="pdf" element={<StampPdfPage />} />
        <Route path="design" element={<LetterheadDesignPage />} />
      </Route>
    </Route>
  )
}

export function pdfToolsRouteTree() {
  return (
    <Route element={<LetterheadRoute />}>
      <Route path="/pdf-tools" element={<PdfToolsPage />}>
        <Route index element={<PdfToolsHome />} />
        <Route path=":tool" element={<PdfToolPage />} />
      </Route>
    </Route>
  )
}

export function tendersRouteTree() {
  return (
    <Route element={<TendersRoute />}>
      <Route path="/tenders" element={<Navigate to="/tenders/gem" replace />} />
      <Route path="/tenders/gem" element={<GemTendersPage />} />
      <Route path="/tenders/mp" element={<MpTendersPage />} />
    </Route>
  )
}

export function attendanceRouteTree() {
  return (
    <Route element={<AttendanceRoute />}>
      <Route path="/attendance" element={<AttendancePage />} />
      <Route path="/attendance/new" element={<AttendanceSheetPage />} />
      <Route path="/attendance/:code" element={<AttendanceSheetPage />} />
    </Route>
  )
}

export function documentsRouteTree() {
  return (
    <Route element={<DocumentsRoute />}>
      <Route path="/documents" element={<DocumentCenterPage />} />
    </Route>
  )
}

export function bankRouteTree() {
  return (
    <Route element={<BankRoute />}>
      <Route path="/bank" element={<BankPage />}>
        <Route index element={<BankOverviewPage />} />
        <Route path="ledger" element={<BankLedgerPage />} />
        <Route path="payables" element={<BankPayablesPage />} />
        <Route path="payroll" element={<BankPayrollPage />} />
        <Route path="reconcile" element={<BankReconcilePage />} />
        <Route path="account" element={<BankAccountPage />} />
      </Route>
    </Route>
  )
}

export function etlRouteTree() {
  return (
    <Route element={<EtlRoute />}>
      <Route path="/etl" element={<EtlPage />} />
    </Route>
  )
}

export function sqlRouteTree() {
  return (
    <Route element={<SqlRoute />}>
      <Route path="/sql" element={<SqlEditorPage />} />
    </Route>
  )
}

export function adminRouteTree() {
  return (
    <Route element={<AdminRoute />}>
      <Route path="/admin" element={<AdminPage />} />
      <Route path="/admin/users/:id" element={<UserPage />} />
    </Route>
  )
}

export function messagesRouteTree() {
  return (
    <>
      <Route path="/messages" element={<MessagesPage />} />
      <Route path="/messages/new/:userId" element={<MessagesPage />} />
      <Route path="/messages/:chatId" element={<MessagesPage />} />
    </>
  )
}

export function tasksRouteTree() {
  return (
    <Route path="/tasks" element={<TasksPage />}>
      <Route index element={<Navigate to="mine" replace />} />
      <Route path="mine" element={<MyWorkPage />} />
      <Route path="todo" element={<TodoPage />} />
      <Route path="projects" element={<ProjectsPage />} />
      <Route path="projects/:key" element={<ProjectPage />} />
      <Route path="reports" element={<TaskReportsPage />} />
      <Route path="inbox" element={<TaskInboxPage />} />
    </Route>
  )
}
