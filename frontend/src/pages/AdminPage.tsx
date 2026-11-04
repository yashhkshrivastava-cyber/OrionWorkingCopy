import { FormEvent, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Users, UserPlus, Settings, ShieldAlert, Mail, Inbox } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useDataRefresh } from '../context/DataRefreshContext'
import { ACCESS_FLAG_KEYS, type AccessFlags, type AppUser, type SignupRequest } from '../types'
import { PageHeader } from '../components/ui/PageHeader'
import { Card, CardHeader } from '../components/ui/Card'
import { Button } from '../components/ui/Button'
import { Alert, Badge } from '../components/ui/Alert'
import { Tabs } from '../components/ui/Tabs'
import { SystemHealthPanel } from '../components/admin/SystemHealthPanel'
import { Field, Input, Select, Checkbox } from '../components/ui/Field'
import { PasswordInput } from '../components/ui/PasswordInput'
import { SearchSelect } from '../components/ui/SearchSelect'
import { DataTable } from '../components/ui/DataTable'
import { UserAvatar } from '../components/UserAvatar'
import { PeopleDirectory, RequestCards } from '../components/admin/LumenPeople'
import { useLumen } from '../lumen/useLumen'

type Tab = 'users' | 'requests' | 'create' | 'manage' | 'system'

const roleBadge: Record<string, 'cyan' | 'violet' | 'amber' | 'rose'> = {
  admin: 'rose',
  editor: 'cyan',
  viewer: 'violet',
}

type DataAccess = AccessFlags

const emptyAccess = (): DataAccess => Object.fromEntries(ACCESS_FLAG_KEYS.map((key) => [key, false])) as DataAccess

/** A user's flags as the form holds them. A flag the API did not send (an older server) is off. */
const accessOf = (user: AppUser): DataAccess =>
  Object.fromEntries(ACCESS_FLAG_KEYS.map((key) => [key, Boolean(user[key])])) as DataAccess

const emptyCreateForm = () => ({
  username: '',
  display_name: '',
  password: '',
  email: '',
  phone: '',
  role: 'viewer',
  ...emptyAccess(),
})

function DataAccessFields({
  value,
  onChange,
}: {
  value: DataAccess
  onChange: (next: DataAccess) => void
}) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <div className="space-y-3 rounded-lg border border-accent/25 bg-accent-dim/50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-accent">
          Operational data
        </p>
        <Checkbox
          label="Review ODS"
          checked={value.ods_access}
          onChange={(ods_access) =>
            onChange({ ...value, ods_access, ods_write: ods_access ? value.ods_write : false })
          }
        />
        <Checkbox
          label="Change ODS — add, edit, delete, upload"
          checked={value.ods_write}
          onChange={(ods_write) => onChange({ ...value, ods_write, ods_access: ods_write ? true : value.ods_access })}
        />
      </div>
      <div className="space-y-3 rounded-md border border-warning/30 bg-warning-dim p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-warning">
          Warehouse
        </p>
        <Checkbox
          label="Browse DW"
          checked={value.dw_access}
          onChange={(dw_access) =>
            onChange({ ...value, dw_access, dw_write: dw_access ? value.dw_write : false })
          }
        />
      </div>
      <div className="space-y-3 rounded-lg border border-violet/25 bg-violet-dim/50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-violet">
          Tally working copy
        </p>
        <Checkbox
          label="Browse Tally ODS"
          checked={value.tally_access}
          onChange={(tally_access) =>
            onChange({ ...value, tally_access, tally_write: tally_access ? value.tally_write : false })
          }
        />
      </div>
      <div className="space-y-3 rounded-lg border border-violet/25 bg-violet-dim/50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-violet">
          Tally warehouse
        </p>
        <Checkbox
          label="Browse Tally DW"
          checked={value.tally_dw_access}
          onChange={(tally_dw_access) =>
            onChange({
              ...value,
              tally_dw_access,
              tally_dw_write: tally_dw_access ? value.tally_dw_write : false,
            })
          }
        />
      </div>
      <div className="space-y-3 rounded-lg border border-accent/25 bg-accent-dim/50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-accent">
          Billing
        </p>
        <Checkbox
          label="View bills, outstanding and monthly billing"
          checked={value.billing_access}
          onChange={(billing_access) =>
            onChange({ ...value, billing_access, billing_write: billing_access ? value.billing_write : false })
          }
        />
        <Checkbox
          label="Raise, edit, cancel, record payments, send"
          checked={value.billing_write}
          onChange={(billing_write) =>
            onChange({ ...value, billing_write, billing_access: billing_write ? true : value.billing_access })
          }
        />
      </div>
      <div className="space-y-3 rounded-lg border border-accent/25 bg-accent-dim/50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-accent">
          Letterhead
        </p>
        <Checkbox
          label="Read and print letters, put a PDF on the letterhead"
          checked={value.letterhead_access}
          onChange={(letterhead_access) =>
            onChange({ ...value, letterhead_access, letterhead_write: letterhead_access ? value.letterhead_write : false })
          }
        />
        <Checkbox
          label="Write, edit and delete letters"
          checked={value.letterhead_write}
          onChange={(letterhead_write) =>
            onChange({ ...value, letterhead_write, letterhead_access: letterhead_write ? true : value.letterhead_access })
          }
        />
      </div>
      <div className="space-y-3 rounded-lg border border-accent/25 bg-accent-dim/50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-accent">
          Documents
        </p>
        <Checkbox
          label="Open and download documents"
          checked={value.documents_access}
          onChange={(documents_access) =>
            onChange({ ...value, documents_access, documents_write: documents_access ? value.documents_write : false })
          }
        />
        <Checkbox
          label="Upload, edit and delete documents, and see Confidential ones"
          checked={value.documents_write}
          onChange={(documents_write) =>
            onChange({ ...value, documents_write, documents_access: documents_write ? true : value.documents_access })
          }
        />
      </div>
      <div className="space-y-3 rounded-lg border border-accent/25 bg-accent-dim/50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-accent">Bank</p>
        <Checkbox
          label="See the bank balance, its ledger, statements and the Cash dashboard"
          checked={value.bank_access}
          onChange={(bank_access) => onChange({ ...value, bank_access, bank_write: bank_access ? value.bank_write : false })}
        />
        <Checkbox
          label="Add and void entries, set the opening balance, upload statements and reconcile"
          checked={value.bank_write}
          onChange={(bank_write) => onChange({ ...value, bank_write, bank_access: bank_write ? true : value.bank_access })}
        />
      </div>
      <div className="space-y-3 rounded-lg border border-accent/25 bg-accent-dim/50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-accent">Tenders</p>
        <Checkbox
          label="See the GeM tender searches and the bids they found"
          checked={value.tenders_access}
          onChange={(tenders_access) => onChange({ ...value, tenders_access, tenders_write: tenders_access ? value.tenders_write : false })}
        />
        <Checkbox
          label="Add and change searches, check GeM now, shortlist and dismiss bids"
          checked={value.tenders_write}
          onChange={(tenders_write) => onChange({ ...value, tenders_write, tenders_access: tenders_write ? true : value.tenders_access })}
        />
      </div>
      <div className="space-y-3 rounded-lg border border-accent/25 bg-accent-dim/50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-accent">Attendance</p>
        <Checkbox
          label="See the attendance registers"
          checked={value.attendance_access}
          onChange={(attendance_access) => onChange({ ...value, attendance_access, attendance_write: attendance_access ? value.attendance_write : false })}
        />
        <Checkbox
          label="Make and change registers, add casual workers, and post a register (which enters the salary lines and expenses)"
          checked={value.attendance_write}
          onChange={(attendance_write) => onChange({ ...value, attendance_write, attendance_access: attendance_write ? true : value.attendance_access })}
        />
      </div>
      <div className="space-y-3 rounded-lg border border-violet/25 bg-violet-dim/50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-violet">AI Copilot</p>
        <Checkbox
          label="Use the AI Copilot. It can only see and do what this person's other permissions allow"
          checked={value.ai_access}
          onChange={(ai_access) => onChange({ ...value, ai_access })}
        />
      </div>
      <div className="space-y-3 rounded-md border border-warning/30 bg-warning-dim p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-warning">
          ETL pipelines
        </p>
        <Checkbox
          label="View pipelines and run history"
          checked={value.etl_access}
          onChange={(etl_access) => onChange({ ...value, etl_access, etl_write: etl_access ? value.etl_write : false })}
        />
        <Checkbox
          label="Run pipelines — load the warehouses and Tally"
          checked={value.etl_write}
          onChange={(etl_write) => onChange({ ...value, etl_write, etl_access: etl_write ? true : value.etl_access })}
        />
      </div>
      <div className="space-y-3 rounded-lg border border-accent/25 bg-accent-dim/50 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-accent">
          Dashboards
        </p>
        <Checkbox
          label="Orion dashboard"
          checked={value.orion_dashboard_access}
          onChange={(orion_dashboard_access) => onChange({ ...value, orion_dashboard_access })}
        />
        <Checkbox
          label="Tally dashboard — billed KPIs from Tally DW"
          checked={value.tally_dashboard_access}
          onChange={(tally_dashboard_access) => onChange({ ...value, tally_dashboard_access })}
        />
      </div>
    </div>
  )
}

export function AdminPage() {
  const { user: currentUser, refresh } = useAuth()
  const { generation } = useDataRefresh()
  const lumen = useLumen()
  const [tab, setTab] = useState<Tab>('users')
  const [users, setUsers] = useState<AppUser[]>([])
  const [signups, setSignups] = useState<{ pending: SignupRequest[]; reviewed: SignupRequest[] }>({
    pending: [],
    reviewed: [],
  })
  const [roles, setRoles] = useState<{ id: string; label: string }[]>([])
  const [defaults, setDefaults] = useState<Record<string, DataAccess>>({})
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const [createForm, setCreateForm] = useState(emptyCreateForm)

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [manageRole, setManageRole] = useState('viewer')
  const [manageAccess, setManageAccess] = useState<DataAccess>(emptyAccess)
  const [manageEmail, setManageEmail] = useState('')
  const [managePhone, setManagePhone] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [selectedRequestId, setSelectedRequestId] = useState<number | null>(null)
  const [requestRole, setRequestRole] = useState('viewer')
  const [requestAccess, setRequestAccess] = useState<DataAccess>(emptyAccess)
  const [rejectReason, setRejectReason] = useState('')

  const load = () => {
    api.users().then(setUsers).catch((e) => setError(e.message))
    api.signups().then(setSignups).catch((e) => setError(e.message))
    api.usersMeta().then((m) => {
      setRoles(m.roles)
      setDefaults(m.default_data_access)
    })
    void refresh()
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reload when the top-bar refresh is pressed (generation); load is a new function every render
  }, [generation])

  const selected = users.find((u) => u.id === selectedId)
  const selectedRequest = signups.pending.find((r) => r.id === selectedRequestId) ?? null
  const roleChanged = Boolean(selected && manageRole !== selected.role)
  const accessChanged = Boolean(selected && ACCESS_FLAG_KEYS.some((key) => manageAccess[key] !== Boolean(selected[key])))
  const contactChanged = Boolean(
    selected &&
      (manageEmail.trim() !== (selected.email || '').trim() ||
        managePhone.trim() !== (selected.phone || '').trim()),
  )
  const passwordReady = newPassword.length > 0 && confirmPassword.length > 0 && newPassword === confirmPassword

  useEffect(() => {
    if (selected) {
      setManageRole(selected.role)
      setManageAccess(accessOf(selected))
      setManageEmail(selected.email || '')
      setManagePhone(selected.phone || '')
      setNewPassword('')
      setConfirmPassword('')
      setConfirmDelete(false)
    }
  }, [selected])

  useEffect(() => {
    if (tab === 'create') {
      setCreateForm(emptyCreateForm())
    }
  }, [tab])

  useEffect(() => {
    const d = defaults[createForm.role]
    if (d) setCreateForm((f) => ({ ...f, ...d }))
  }, [createForm.role, defaults])

  useEffect(() => {
    setRequestRole('viewer')
    setRejectReason('')
  }, [selectedRequestId])

  useEffect(() => {
    const d = defaults[requestRole]
    if (d) setRequestAccess({ ...emptyAccess(), ...d })
  }, [requestRole, defaults])

  useEffect(() => {
    if (!message) return
    const timer = window.setTimeout(() => setMessage(''), 4000)
    return () => window.clearTimeout(timer)
  }, [message])

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    setMessage('')
    setSubmitting(true)
    try {
      await api.createUser(createForm)
      setMessage(`User "${createForm.username}" created.`)
      setCreateForm(emptyCreateForm())
      load()
      setTab('users')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed')
    } finally {
      setSubmitting(false)
    }
  }

  const runAction = async (fn: () => Promise<unknown>, success: string, refreshSelf = false) => {
    setError('')
    setMessage('')
    setSubmitting(true)
    try {
      await fn()
      if (success) setMessage(success)
      load()
      if (refreshSelf) await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed')
    } finally {
      setSubmitting(false)
    }
  }

  const userTableRows = users.map((u) => ({
    Username: u.username,
    'Display Name': u.display_name,
    Email: u.email || '—',
    Phone: u.phone || '—',
    Role: u.role,
    ODS: u.ods_write ? 'Change' : u.ods_access ? 'Review' : '—',
    DW: u.dw_access ? 'Browse' : '—',
    Tally: u.tally_access ? 'Browse' : '—',
    'Tally DW': u.tally_dw_access ? 'Browse' : '—',
    Billing: u.billing_write ? 'Change' : u.billing_access ? 'View' : '—',
    Letterhead: u.letterhead_write ? 'Write' : u.letterhead_access ? 'Read' : '—',
    Documents: u.documents_write ? 'Change' : u.documents_access ? 'Read' : '—',
    Bank: u.bank_write ? 'Change' : u.bank_access ? 'View' : '—',
    Tenders: u.tenders_write ? 'Change' : u.tenders_access ? 'View' : '—',
    Attendance: u.attendance_write ? 'Change' : u.attendance_access ? 'View' : '—',
    'AI Copilot': u.ai_access ? 'On' : 'Off',
    ETL: u.etl_write ? 'Run' : u.etl_access ? 'View' : '—',
    Dashboards: [u.orion_dashboard_access && 'Orion', u.tally_dashboard_access && 'Tally']
      .filter(Boolean)
      .join(' · ') || '—',
    Status: u.is_active ? 'Active' : 'Disabled',
  }))

  return (
    <div className="space-y-6">
      <PageHeader
        title="User administration"
        subtitle="Manage accounts, access requests, roles, and data access."
        action={
          <div className="flex items-center gap-2 rounded-lg border border-violet/25 bg-violet-dim px-3 py-2">
            <Users className="h-4 w-4 text-violet" />
            <span className="text-sm font-medium text-violet">{users.length} users</span>
          </div>
        }
      />

      <Tabs
        tabs={[
          { id: 'users' as Tab, label: 'All users' },
          {
            id: 'requests' as Tab,
            label: signups.pending.length ? `Requests (${signups.pending.length})` : 'Requests',
          },
          { id: 'create' as Tab, label: 'Create user' },
          { id: 'manage' as Tab, label: 'Manage user' },
          { id: 'system' as Tab, label: 'System' },
        ]}
        active={tab}
        onChange={setTab}
      />

      {error && <Alert variant="error" onDismiss={() => setError('')}>{error}</Alert>}
      {message && <Alert variant="success" onDismiss={() => setMessage('')}>{message}</Alert>}

      {tab === 'system' && <SystemHealthPanel />}

      {tab === 'users' && lumen && (
        <PeopleDirectory
          users={users}
          pending={signups.pending.length}
          onManage={(id) => {
            setSelectedId(id)
            setTab('manage')
          }}
          onRequests={() => setTab('requests')}
        />
      )}

      {tab === 'users' && !lumen && (
        <Card accent="blue">
          <CardHeader title="Users" subtitle="Everyone with access to this workspace" />
          <DataTable
            columns={['Username', 'Display Name', 'Email', 'Phone', 'Role', 'ODS', 'DW', 'Tally', 'Tally DW', 'Status']}
            rows={userTableRows}
            emptyMessage="No users found."
            filterable
          />
        </Card>
      )}

      {tab === 'requests' && lumen && <RequestCards requests={signups.pending} selectedId={selectedRequestId} onSelect={setSelectedRequestId} />}

      {tab === 'requests' && (
        <>
          {!lumen && (
          <Card accent="violet">
            <CardHeader
              title="Account requests"
              subtitle="People who asked for access from the login page. Approve with a role and data access, or reject."
              action={<Inbox className="h-5 w-5 text-violet" />}
            />
            {signups.pending.length === 0 ? (
              <p className="text-sm text-[color:var(--color-text-muted)]">No requests waiting.</p>
            ) : (
              <Field label="Select request">
                <SearchSelect
                  value={selectedRequestId != null ? String(selectedRequestId) : ''}
                  options={signups.pending.map((r) => ({
                    id: String(r.id),
                    label: `${r.display_name} (${r.username})`,
                  }))}
                  placeholder="— Choose a request —"
                  onChange={(next) => setSelectedRequestId(next ? Number(next) : null)}
                />
              </Field>
            )}
          </Card>
          )}

          {selectedRequest && (
            <div className="grid gap-5">
              <Card accent="violet">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="text-lg font-semibold">{selectedRequest.display_name}</h3>
                    <p className="text-sm text-[color:var(--color-text-muted)]">@{selectedRequest.username}</p>
                    <p className="mt-2 text-sm">
                      {selectedRequest.email}
                      {selectedRequest.phone ? ` · ${selectedRequest.phone}` : ''}
                    </p>
                    <p className="mt-1 text-xs text-[color:var(--color-text-faint)]">
                      Requested {new Date(selectedRequest.requested_timestamp).toLocaleString()}
                    </p>
                  </div>
                  <Badge variant="amber">Pending</Badge>
                </div>
              </Card>

              <Card accent="blue">
                <CardHeader title="Access to grant" subtitle="Choose the role and stores this person may use after approval" />
                <Field label="Role" className="mb-4">
                  <Select value={requestRole} onChange={(e) => setRequestRole(e.target.value)}>
                    {roles.map((r) => (
                      <option key={r.id} value={r.id}>{r.label}</option>
                    ))}
                  </Select>
                </Field>
                <DataAccessFields value={requestAccess} onChange={setRequestAccess} />
                <div className="mt-5 flex flex-wrap gap-2">
                  <Button
                    loading={submitting}
                    onClick={() =>
                      runAction(
                        async () => {
                          await api.approveSignup(selectedRequest.id, {
                            role: requestRole,
                            ...requestAccess,
                          })
                          setSelectedRequestId(null)
                          await refresh()
                        },
                        `Account created. A ready-to-use email was sent to ${selectedRequest.email}.`,
                      )
                    }
                  >
                    Approve and create account
                  </Button>
                </div>
              </Card>

              <Card accent="rose">
                <CardHeader title="Reject" subtitle="The request is closed. They can submit again with a different username if needed." />
                <Field label="Reason (optional)" className="mb-4">
                  <Input
                    value={rejectReason}
                    onChange={(e) => setRejectReason(e.target.value)}
                    placeholder="Not needed for this workspace"
                  />
                </Field>
                <Button
                  variant="secondary"
                  loading={submitting}
                  onClick={() =>
                    runAction(
                      async () => {
                        await api.rejectSignup(selectedRequest.id, rejectReason.trim() || undefined)
                        setSelectedRequestId(null)
                        await refresh()
                      },
                      'Request rejected.',
                    )
                  }
                >
                  Reject request
                </Button>
              </Card>
            </div>
          )}

          {signups.reviewed.length > 0 && (
            <Card>
              <CardHeader title="Recently reviewed" subtitle="Approved and rejected requests" />
              <DataTable
                columns={['Name', 'Username', 'Email', 'Status', 'Reviewed']}
                rows={signups.reviewed.map((r) => ({
                  Name: r.display_name,
                  Username: r.username,
                  Email: r.email,
                  Status: r.status === 'approved' ? 'Approved' : 'Rejected',
                  Reviewed: r.reviewed_timestamp ? new Date(r.reviewed_timestamp).toLocaleString() : '—',
                }))}
                filterable
                emptyMessage="None yet."
              />
            </Card>
          )}
        </>
      )}

      {tab === 'create' && (
        <Card accent="teal">
          <CardHeader
            title="Create user"
            subtitle="Add an account with a role and data access"
            action={<UserPlus className="h-5 w-5 text-accent" />}
          />
          <form onSubmit={handleCreate} className="space-y-5" autoComplete="off">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Username">
                <Input
                  value={createForm.username}
                  onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })}
                  placeholder="jane.doe"
                  autoComplete="off"
                  name="orion-new-username"
                />
              </Field>
              <Field label="Display name">
                <Input
                  value={createForm.display_name}
                  onChange={(e) => setCreateForm({ ...createForm, display_name: e.target.value })}
                  placeholder="Jane Doe"
                  autoComplete="off"
                />
              </Field>
              <Field label="Email">
                <Input
                  type="email"
                  value={createForm.email}
                  onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })}
                  placeholder="jane@company.com"
                  autoComplete="off"
                />
              </Field>
              <Field label="Phone">
                <Input
                  type="tel"
                  value={createForm.phone}
                  onChange={(e) => setCreateForm({ ...createForm, phone: e.target.value })}
                  placeholder="+91 9876543210"
                  autoComplete="off"
                />
              </Field>
              <Field label="Password">
                <PasswordInput
                  value={createForm.password}
                  onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                  autoComplete="new-password"
                  name="orion-new-password"
                />
              </Field>
              <Field label="Role">
                <Select
                  value={createForm.role}
                  onChange={(e) => setCreateForm({ ...createForm, role: e.target.value })}
                >
                  {roles.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <DataAccessFields
              value={createForm}
              onChange={(access) => setCreateForm({ ...createForm, ...access })}
            />
            <Button type="submit" loading={submitting}>
              Create user
            </Button>
          </form>
        </Card>
      )}

      {tab === 'manage' && (
        <>
          <Card padding="sm">
            <Field label="Select user">
              <SearchSelect
                value={selectedId != null ? String(selectedId) : ''}
                options={users.map((u) => ({
                  id: String(u.id),
                  label: `${u.display_name} (${u.username})`,
                }))}
                placeholder="— Choose a user —"
                onChange={(next) => setSelectedId(next ? Number(next) : null)}
              />
            </Field>
          </Card>

          {selected && (
            <div className="grid gap-5 lg:grid-cols-2">
              {/* Profile card */}
              <Card className="lg:col-span-2" accent="violet">
                <div className="flex items-center gap-4">
                  <UserAvatar user={selected} size="lg" />
                  <div>
                    <h3 className="text-lg font-semibold">{selected.display_name}</h3>
                    <p className="text-sm text-[color:var(--color-text-muted)]">@{selected.username}</p>
                    <div className="mt-2 flex gap-2">
                      <Badge variant={roleBadge[selected.role] || 'default'}>{selected.role}</Badge>
                      <Badge variant={selected.is_active ? 'emerald' : 'rose'}>
                        {selected.is_active ? 'Active' : 'Disabled'}
                      </Badge>
                    </div>
                  </div>
                  <Link to={`/admin/users/${selected.id}`} className="ml-auto text-sm font-semibold text-accent hover:underline">
                    Open the account page
                  </Link>
                </div>
              </Card>

              <Card accent="blue">
                <CardHeader title="Role & status" subtitle="Access level and account state" action={<Settings className="h-4 w-4 text-accent" />} />
                <Field label="Role" className="mb-4">
                  <Select value={manageRole} onChange={(e) => setManageRole(e.target.value)}>
                    {roles.map((r) => (
                      <option key={r.id} value={r.id}>{r.label}</option>
                    ))}
                  </Select>
                </Field>
                <div className="flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    loading={submitting}
                    disabled={!roleChanged}
                    onClick={() =>
                      runAction(
                        () => api.updateUserRole(selected.id, manageRole),
                        'Role updated.',
                        selected.id === currentUser?.id,
                      )
                    }
                  >
                    Update role
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={submitting}
                    onClick={() =>
                      runAction(
                        () => api.updateUserActive(selected.id, !selected.is_active),
                        selected.is_active ? 'User disabled.' : 'User enabled.',
                      )
                    }
                  >
                    {selected.is_active ? 'Disable' : 'Enable'}
                  </Button>
                </div>
              </Card>

              <Card className="lg:col-span-2" accent="teal">
                <CardHeader title="Data access" subtitle="What this person can see and write in Data management, including Tally Prime" />
                <div className="mb-4">
                  <DataAccessFields value={manageAccess} onChange={setManageAccess} />
                </div>
                <Button
                  size="sm"
                  loading={submitting}
                  disabled={!accessChanged}
                  onClick={() =>
                    runAction(
                      () => api.updateUserDataAccess(selected.id, manageAccess),
                      'Data access updated.',
                      selected.id === currentUser?.id,
                    )
                  }
                >
                  Update data access
                </Button>
              </Card>

              <Card accent="teal">
                <CardHeader title="Contact" subtitle="Email and phone for password recovery" />
                <div className="mb-4 grid gap-4 sm:grid-cols-2">
                  <Field label="Email">
                    <Input
                      type="email"
                      value={manageEmail}
                      onChange={(e) => setManageEmail(e.target.value)}
                      placeholder="user@company.com"
                    />
                  </Field>
                  <Field label="Phone">
                    <Input
                      type="tel"
                      value={managePhone}
                      onChange={(e) => setManagePhone(e.target.value)}
                      placeholder="+91 9876543210"
                    />
                  </Field>
                </div>
                <Button
                  size="sm"
                  loading={submitting}
                  disabled={!contactChanged}
                  onClick={() =>
                    runAction(
                      () => api.updateUserContact(selected.id, { email: manageEmail, phone: managePhone }),
                      'Contact details updated.',
                    )
                  }
                >
                  Update contact
                </Button>
              </Card>

              <Card accent="amber">
                <CardHeader
                  title="Reset password"
                  subtitle="Set a password here, or email the same one-hour link as Forgot password"
                  action={<Mail className="h-4 w-4 text-warning" />}
                />
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="New password">
                    <PasswordInput value={newPassword} onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" />
                  </Field>
                  <Field label="Confirm password">
                    <PasswordInput value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} autoComplete="new-password" />
                  </Field>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    loading={submitting}
                    disabled={!passwordReady}
                    onClick={() => {
                      runAction(() => api.updateUserPassword(selected.id, newPassword), 'Password updated.').then(
                        () => {
                          setNewPassword('')
                          setConfirmPassword('')
                        },
                      )
                    }}
                  >
                    Update password
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={submitting}
                    disabled={!selected.email || !selected.is_active}
                    onClick={() =>
                      runAction(async () => {
                        const result = await api.sendUserPasswordReset(selected.id)
                        setMessage(`Reset link sent to ${result.email}. It expires in one hour.`)
                      }, '')
                    }
                  >
                    Send reset link
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={submitting}
                    title="Ends every place this person is signed in. They can sign in again unless the account is disabled."
                    onClick={() =>
                      runAction(async () => {
                        const result = await api.signOutUserEverywhere(selected.id)
                        setMessage(
                          result.ended
                            ? `Signed ${selected.display_name} out of ${result.ended} ${result.ended === 1 ? 'place' : 'places'}.`
                            : `${selected.display_name} was not signed in anywhere.`,
                        )
                      }, '')
                    }
                  >
                    Sign out everywhere
                  </Button>
                </div>
                {!selected.email ? (
                  <p className="mt-3 text-xs text-[color:var(--color-text-muted)]">
                    Add an email under Contact before sending a reset link.
                  </p>
                ) : !selected.is_active ? (
                  <p className="mt-3 text-xs text-[color:var(--color-text-muted)]">
                    Enable this account before sending a reset link.
                  </p>
                ) : (
                  <p className="mt-3 text-xs text-[color:var(--color-text-muted)]">
                    The link is emailed to {selected.email}.
                  </p>
                )}
              </Card>

              <Card className="border-negative/30" accent="rose">
                <CardHeader
                  title="Delete user"
                  subtitle="This cannot be undone"
                  action={<ShieldAlert className="h-4 w-4 text-negative" />}
                />
                <Checkbox
                  label="I confirm permanent deletion of this user"
                  checked={confirmDelete}
                  onChange={setConfirmDelete}
                />
                <Button
                  variant="danger"
                  size="sm"
                  className="mt-4"
                  disabled={!confirmDelete}
                  loading={submitting}
                  onClick={() =>
                    runAction(() => api.deleteUser(selected.id), 'User deleted.').then(() => {
                      setSelectedId(null)
                      setConfirmDelete(false)
                    })
                  }
                >
                  Delete user
                </Button>
              </Card>
            </div>
          )}
        </>
      )}
    </div>
  )
}
