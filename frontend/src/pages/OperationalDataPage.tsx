import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { Briefcase, Car, Coins, History, Pencil, Plus, RefreshCw, Settings2, Upload, Users, X } from 'lucide-react'
import { api, ApiError } from '../api/client'
import { newIdempotencyKey } from '../api/idempotency'
import { useAuth } from '../context/AuthContext'
import { useDataRefresh } from '../context/DataRefreshContext'
import { FillFromText } from '../components/ai/FillFromText'
import { EntityForm } from '../components/EntityForm'
import { ExcelUploadPanel } from '../components/ExcelUploadPanel'
import { PreviewRecords } from '../components/PreviewRecords'
import type { EntityMeta } from '../types'
import { requiredFieldError, payloadFromValues, fieldChanges, fieldPreview, formatFieldValue, type FieldChange } from '../formPayload'
import { WorkbenchPlace, WorkbenchPanel, WorkbenchShell, WorkbenchStage } from '../components/data/WorkbenchChrome'
import { WorkbenchCatalog, type CatalogGroup } from '../components/data/WorkbenchCatalog'
import { Button } from '../components/ui/Button'
import { Alert } from '../components/ui/Alert'
import { Field, Checkbox } from '../components/ui/Field'
import { SearchSelect } from '../components/ui/SearchSelect'
import { Modal } from '../components/ui/Modal'
import { RecordHistoryModal } from '../components/data/RecordHistoryModal'
import { DOCUMENT_KINDS, EmployeeDocuments, type StagedDocument } from '../components/data/EmployeeDocuments'
import { WriteGate } from '../components/data/WriteGate'
import { useLumen } from '../lumen/useLumen'
import { useFollowups } from '../context/FollowupsContext'

type Action = 'Create' | 'Update' | 'Upload'

const DATASET_GROUPS: { label: string; names: string[]; icon: typeof Settings2 }[] = [
  { label: 'Setup', names: ['Business Domain', 'Capability', 'Expense Type'], icon: Settings2 },
  { label: 'Clients & work', names: ['Client', 'Contact', 'Case', 'Opportunity'], icon: Briefcase },
  { label: 'People', names: ['Employee', 'Employee Transaction'], icon: Users },
  { label: 'Fleet', names: ['Car', 'Car Transaction'], icon: Car },
  { label: 'Money', names: ['Transaction', 'Expense Transaction', 'EMD'], icon: Coins },
]

/** An entity's name as it reads in a sentence: lower case, except an acronym such as EMD. */
function entityNoun(name: string): string {
  return name === name.toUpperCase() ? name : name.toLowerCase()
}

function groupDatasets(entities: EntityMeta[]): CatalogGroup[] {
  const known = new Set(entities.map((entity) => entity.name))
  const used = new Set<string>()
  const groups: CatalogGroup[] = []

  for (const group of DATASET_GROUPS) {
    const Icon = group.icon
    const items = group.names
      .filter((name) => known.has(name))
      .map((name) => ({ id: name, label: name }))
    items.forEach((item) => used.add(item.id))
    if (items.length) groups.push({ label: group.label, icon: <Icon className="h-3.5 w-3.5" />, items })
  }

  const rest = entities
    .filter((entity) => !used.has(entity.name))
    .map((entity) => ({ id: entity.name, label: entity.name }))
  if (rest.length) groups.push({ label: 'Other', items: rest })
  return groups
}

export function OperationalDataPage() {
  const { user, loading } = useAuth()
  const lumen = useLumen()
  const { generation } = useDataRefresh()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const wantsChange = searchParams.get('intent') === 'change'
  // The page this was opened from (a client's, a case's), for the way back; only a page of Orion data.
  const returnParam = searchParams.get('return')
  const returnTo = returnParam && /^\/data\/[A-Za-z0-9/_-]+$/.test(returnParam) ? returnParam : null
  const canWrite = Boolean(user?.can_ods_write)
  const changeIntent = wantsChange && canWrite
  const [changeUnlocked, setChangeUnlocked] = useState(
    () => Boolean((location.state as { writeAck?: boolean } | null)?.writeAck),
  )
  const canChange = changeIntent && changeUnlocked
  const followups = useFollowups()
  const [entities, setEntities] = useState<EntityMeta[]>([])
  /** Set when the form was opened from a notification about a won opportunity: the opportunity is fixed, and an EMD offers only its cases. */
  const [followup, setFollowup] = useState<{ entity: string; code: string; name: string; cases: { id: string; label: string }[] } | null>(null)
  const [selectedEntity, setSelectedEntity] = useState('')
  const [action, setAction] = useState<Action | null>(null)
  const [previewTick, setPreviewTick] = useState(0)
  const [formValues, setFormValues] = useState<Record<string, unknown>>({})
  const [originalValues, setOriginalValues] = useState<Record<string, unknown> | null>(null)
  // The server marks a record that another feature owns (a bill's revenue entry) and says why.
  const lockedReason =
    action === 'Update' && typeof formValues.__locked === 'string' ? formValues.__locked : ''
  const [recordOptions, setRecordOptions] = useState<{ id: string; label: string }[]>([])
  const [selectedRecordId, setSelectedRecordId] = useState('')
  /** Documents chosen on the Add screen for an employee that is not saved yet. */
  const [stagedDocs, setStagedDocs] = useState<StagedDocument[]>([])
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  /** Someone else saved the record being edited after it was opened here, so the save was refused. */
  const [stale, setStale] = useState(false)
  /** The record whose history is open. A row in the table or the Update screen sets it. */
  const [historyFor, setHistoryFor] = useState<{ id: string; label: string } | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // One key for each time a new record is reviewed: confirming twice, or a retry, saves (and pays) it once.
  const createKey = useRef(newIdempotencyKey())
  /** What the Add form opened from another page starts with (a case for this client); the reset below would otherwise empty it. */
  const fillOnOpen = useRef<Record<string, unknown> | null>(null)
  const [pending, setPending] = useState<
    | { kind: 'create' | 'delete'; rows: { key: string; label: string; value: string }[]; duplicates?: { expense_code: string; note: string }[] }
    | { kind: 'update'; rows: (FieldChange & { fromLabel: string; toLabel: string })[] }
    | null
  >(null)

  useEffect(() => {
    if (!user?.can_ods) return
    let cancelled = false
    const load = () => {
      api.entities().then((r) => {
        if (cancelled) return
        setEntities(r.entities)
        setSelectedEntity((current) =>
          current && r.entities.some((entity) => entity.name === current)
            ? current
            : r.entities[0]?.name ?? '',
        )
      })
    }
    load()
    const onVisible = () => {
      if (document.visibilityState === 'visible') load()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', load)
    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', load)
    }
  }, [user, generation])

  const refreshPreview = () => setPreviewTick((n) => n + 1)

  useEffect(() => {
    if (action !== 'Update') {
      setRecordOptions([])
      // A form opened from a notification starts with the opportunity filled in; nothing else clears it.
      if (!followup) {
        setFormValues(fillOnOpen.current ?? {})
        fillOnOpen.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a change of record type or action starts the form again, not the follow-up being set with them
  }, [selectedEntity, action])

  /** Opens the form that settles a follow-up (a new case or EMD) with the won opportunity already chosen. */
  const startFollowup = useCallback(
    async (entity: string, code: string) => {
      try {
        const found = await api.followupContext(code)
        const name = found.opportunity.opportunity_name || code
        const prefill: Record<string, unknown> = { opportunity_code: code }
        if (entity === 'Case') prefill.case_name = name
        if (entity === 'EMD') {
          if (found.cases.length === 1) prefill.case_code = found.cases[0].id
          if (found.opportunity.tender_id) prefill.tender_reference = found.opportunity.tender_id
        }
        setFollowup({ entity, code, name, cases: found.cases })
        setSelectedEntity(entity)
        setFormValues(prefill)
        setOriginalValues(null)
        setSelectedRecordId('')
        setPending(null)
        setError('')
        setMessage('')
        setAction('Create')
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not open the form')
      }
    },
    [],
  )

  // The address of a notification names the form to open: ?intent=change&entity=Case&mode=create&opportunity=OPP-0001. It is opened once.
  const opened = useRef('')
  useEffect(() => {
    const entity = searchParams.get('entity')
    const code = searchParams.get('opportunity')
    if (!canChange || !entities.length || searchParams.get('mode') !== 'create' || !entity || !code) return
    const key = `${entity}:${code}`
    if (opened.current === key || !entities.some((item) => item.name === entity)) return
    opened.current = key
    void startFollowup(entity, code)
  }, [canChange, entities, searchParams, startFollowup])

  // The data desk opens a form straight away: ?entity=Employee (look at its records) or ?intent=change&entity=Employee&mode=create (the Add form, once the change warning is accepted). It is opened once.
  const deepLinked = useRef('')
  useEffect(() => {
    const entity = searchParams.get('entity')
    if (!entity || searchParams.get('opportunity') || !entities.some((item) => item.name === entity)) return
    const mode = searchParams.get('mode')
    const opens: Action | null = !canChange ? null : mode === 'create' ? 'Create' : mode === 'edit' ? 'Update' : mode === 'upload' ? 'Upload' : null
    const record = searchParams.get('record') ?? ''
    const fills = searchParams.getAll('fill')
    const key = `${entity}:${opens}:${record}:${fills.join('|')}`
    if (deepLinked.current === key) return
    deepLinked.current = key
    setSelectedEntity(entity)
    if (opens) {
      // Only fields the record type has can be filled in, so an address cannot put a value anywhere else.
      const meta = entities.find((item) => item.name === entity)
      const known = new Set([...Object.keys(meta?.form_fields ?? {}), ...Object.keys(meta?.create_fields ?? {})])
      const fill: Record<string, unknown> = {}
      for (const entry of fills) {
        const at = entry.indexOf(':')
        const field = entry.slice(0, at)
        if (at > 0 && known.has(field)) fill[field] = entry.slice(at + 1).slice(0, 200)
      }
      fillOnOpen.current = opens === 'Create' && Object.keys(fill).length ? fill : null
      setFormValues({})
      setOriginalValues(null)
      setSelectedRecordId(opens === 'Update' ? record.slice(0, 40) : '')
      setPending(null)
      setAction(opens)
    }
  }, [entities, searchParams, canChange])

  useEffect(() => {
    if (!selectedEntity || action !== 'Update') return
    api.entityOptions(selectedEntity).then(setRecordOptions)
  }, [selectedEntity, action, generation])

  useEffect(() => {
    if (!selectedRecordId || action !== 'Update') return
    api
      .getRecord(selectedEntity, selectedRecordId)
      .then((r) => {
        setFormValues(r)
        setOriginalValues(r)
        setStale(false)
      })
      .catch((e) => setError(e.message))
  }, [selectedRecordId, selectedEntity, action])

  useEffect(() => {
    if (!message) return
    const timer = window.setTimeout(() => setMessage(''), 4000)
    return () => window.clearTimeout(timer)
  }, [message])

  useEffect(() => {
    setConfirmDelete(false)
    setPending(null)
  }, [selectedRecordId, selectedEntity, action])

  // Before the early returns below: a hook must run on every render, or React counts a different number of them when `loading` flips.
  const datasetGroups = useMemo(() => groupDatasets(entities), [entities])

  if (loading) return null
  if (!user?.can_ods) return <Navigate to="/data/orion" replace />
  if (wantsChange && !canWrite) return <Navigate to="/data/operational" replace />

  const currentMeta = entities.find((e) => e.name === selectedEntity)
  // Adding a record may ask more than editing it does (an expense: has it been paid, and from where).
  const formFields = currentMeta ? (action === 'Create' && currentMeta.create_fields ? { ...currentMeta.form_fields, ...currentMeta.create_fields } : currentMeta.form_fields) : {}
  const selectedRecordLabel =
    recordOptions.find((option) => option.id === selectedRecordId)?.label || selectedRecordId

  /** A row of the records table: its code is the primary key, and its name column labels the dialog. */
  const openHistoryFromRow = (row: Record<string, unknown>) => {
    if (!currentMeta) return
    const id = row[currentMeta.primary_key]
    if (id === undefined || id === null || id === '') return
    const name = row[currentMeta.display_column]
    setHistoryFor({ id: String(id), label: name ? `${String(name)} (${String(id)})` : String(id) })
  }

  const lookupLabel = async (key: string, value: unknown, cache: Record<string, { id: string; label: string }[]>) => {
    if (value == null || value === '') return '—'
    if (!cache[key]) cache[key] = await api.fieldOptions(selectedEntity, key)
    return cache[key].find((option) => String(option.id).trim() === String(value).trim())?.label || String(value)
  }

  const previewRows = async (values: Record<string, unknown>) => {
    if (!currentMeta) return []
    const cache: Record<string, { id: string; label: string }[]> = {}
    return Promise.all(
      fieldPreview(formFields, values).map(async (field) => ({
        key: field.key,
        label: field.label,
        value: field.lookup
          ? await lookupLabel(field.key, field.value, cache)
          : formatFieldValue(field.value, field.type, field.labels),
      })),
    )
  }

  const handleSubmit = async () => {
    setError('')
    setMessage('')
    if (!currentMeta) return
    const missing = requiredFieldError(formFields, formValues)
    if (missing) {
      setError(missing)
      return
    }

    setSubmitting(true)
    const cache: Record<string, { id: string; label: string }[]> = {}
    try {
      if (action === 'Create') {
        const rows = await previewRows(formValues)
        if (DOCUMENT_KINDS[selectedEntity] && stagedDocs.length) {
          rows.push({
            key: 'documents',
            label: 'Documents',
            value: stagedDocs.map((item) => `${item.docType}${item.title ? ` (${item.title})` : ''}: ${item.file.name}`).join(', '),
          })
        }
        createKey.current = newIdempotencyKey()
        // A record that looks like one already entered is warned about here, with the values; it is never refused.
        let duplicates: { expense_code: string; note: string }[] = []
        if (currentMeta.checks_duplicates) {
          try {
            duplicates = (await api.duplicateCheck(selectedEntity, payloadFromValues(formFields, formValues))).matches
          } catch {
            duplicates = [] // the check is a courtesy: a failure of it must not stop the save
          }
        }
        setPending({ kind: 'create', rows, duplicates })
        return
      }

      const changes = fieldChanges(currentMeta.form_fields, originalValues ?? {}, formValues)
      if (!changes.length) {
        setError('No changes to save.')
        return
      }
      const rows = await Promise.all(
        changes.map(async (change) => ({
          ...change,
          fromLabel: change.lookup
            ? await lookupLabel(change.key, change.from, cache)
            : formatFieldValue(change.from, change.type, change.labels),
          toLabel: change.lookup
            ? await lookupLabel(change.key, change.to, cache)
            : formatFieldValue(change.to, change.type, change.labels),
        })),
      )
      setPending({ kind: 'update', rows })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not prepare the confirmation')
    } finally {
      setSubmitting(false)
    }
  }

  const applyPending = async () => {
    if (!currentMeta || !pending) return
    setSubmitting(true)
    try {
      if (pending.kind === 'create') {
        const created = await api.createRecord(selectedEntity, payloadFromValues(formFields, formValues), createKey.current)
        setFormValues({})
        const documentKind = DOCUMENT_KINDS[selectedEntity]
        const queued = documentKind ? stagedDocs : []
        setStagedDocs([])
        if (queued.length && created.id) {
          // The employee is saved. Its documents go up one by one, and any that fail are named so they can be added from Edit.
          const failed: string[] = []
          for (const item of queued) {
            try {
              await (documentKind === 'emd' ? api.uploadEmdDocument : api.uploadEmployeeDocument)(created.id, item.file, item.docType, item.title)
            } catch (e) {
              failed.push(`${item.file.name} (${e instanceof Error ? e.message : 'not uploaded'})`)
            }
          }
          setMessage(
            failed.length
              ? `${selectedEntity} ${created.id} created. ${queued.length - failed.length} of ${queued.length} documents uploaded. Not uploaded: ${failed.join('; ')}. Add them from Edit.`
              : `${selectedEntity} ${created.id} created with ${queued.length} document${queued.length === 1 ? '' : 's'}.`,
          )
        } else {
          setMessage('Record created successfully.')
        }
      } else if (pending.kind === 'delete') {
        await api.deleteRecord(selectedEntity, selectedRecordId)
        setSelectedRecordId('')
        setFormValues({})
        setOriginalValues(null)
        setConfirmDelete(false)
        api.entityOptions(selectedEntity).then(setRecordOptions)
        setMessage('Record deleted.')
      } else {
        // Only what was changed is sent, with the version of the record that was opened: a field this person did not touch is
        // never written back from a copy that may be out of date, and a record saved by someone else since is not overwritten.
        const changed = new Set(pending.rows.map((row) => row.key))
        const data = Object.fromEntries(
          Object.entries(payloadFromValues(currentMeta.form_fields, formValues)).filter(([key]) => changed.has(key)),
        )
        const opened = originalValues?.last_updated_timestamp
        await api.updateRecord(selectedEntity, selectedRecordId, data, typeof opened === 'string' ? opened : undefined)
        setOriginalValues(formValues)
        setMessage('Record updated successfully.')
      }
      setPending(null)
      closeForm()
      refreshPreview()
      void followups.refresh() // a win saved here asks for its case and EMD at once; a case or EMD saved here settles its notification
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Operation failed')
      setStale(e instanceof ApiError && e.status === 409 && pending.kind === 'update')
      setPending(null)
    } finally {
      setSubmitting(false)
    }
  }

  /** Opens the record again as it is now, for someone whose save was refused because it had been changed. */
  const reloadRecord = async () => {
    if (!selectedRecordId) return
    try {
      const fresh = await api.getRecord(selectedEntity, selectedRecordId)
      setFormValues(fresh)
      setOriginalValues(fresh)
      setError('')
      setStale(false)
      setMessage('Opened again with the latest values. Make your change again.')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not open the record')
    }
  }

  const handleDelete = async () => {
    setError('')
    setMessage('')
    if (!confirmDelete) {
      setError('Please confirm deletion first.')
      return
    }
    if (!currentMeta || !selectedRecordId) return
    setSubmitting(true)
    try {
      setPending({ kind: 'delete', rows: await previewRows(originalValues ?? formValues) })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not prepare the confirmation')
    } finally {
      setSubmitting(false)
    }
  }

  const closeForm = () => {
    setFollowup(null)
    setAction(null)
    setFormValues({})
    setOriginalValues(null)
    setSelectedRecordId('')
    setConfirmDelete(false)
    setStagedDocs([])
    setError('')
    setStale(false)
  }

  const selectEntity = (next: string) => {
    setSelectedEntity(next)
    closeForm()
    setPending(null)
    setMessage('')
  }

  const openWrite = (next: Action) => {
    if (!canChange) return
    setError('')
    setMessage('')
    setFormValues({})
    setOriginalValues(null)
    setSelectedRecordId('')
    setConfirmDelete(false)
    setPending(null)
    setAction(next)
  }

  const formOpen = Boolean(action && currentMeta)

  return (
    <WorkbenchShell>
      <WorkbenchPlace
        tone="teal"
        backTo={returnTo ?? '/data/orion'}
        backLabel={returnTo ? (searchParams.get('returnLabel') ?? 'Back').slice(0, 30) : 'Orion'}
        here={canChange ? 'Change operational data' : 'Review operational data'}
        item={selectedEntity || undefined}
      />

      {currentMeta && (
        <WorkbenchStage
          catalog={
            <WorkbenchCatalog
              tone="teal"
              groups={datasetGroups}
              selected={selectedEntity}
              onSelect={selectEntity}
            />
          }
          main={
            formOpen ? (
              <WorkbenchPanel fill className="gap-0 p-0">
                {lumen ? (
                  <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-[color:var(--color-border)] px-5 pb-4 pt-5">
                    <span style={{ '--hue': 'var(--orion-accent)' } as React.CSSProperties} className="lumen-chip grid h-12 w-12 shrink-0 place-items-center rounded-2xl">
                      {action === 'Create' ? <Plus className="h-6 w-6" /> : action === 'Update' ? <Pencil className="h-5 w-5" /> : <Upload className="h-5 w-5" />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <h2 className="font-display text-xl font-semibold leading-tight">
                        {action === 'Create'
                        ? `New ${entityNoun(selectedEntity)}`
                        : action === 'Update'
                          ? `Edit ${entityNoun(selectedEntity)}`
                          : `Upload ${entityNoun(selectedEntity)}`}
                      </h2>
                      <p className="t-caption mt-0.5 text-[color:var(--color-text-muted)]">
                        {action === 'Create'
                          ? 'Fill in the details. Nothing is saved until you press Create record.'
                          : action === 'Update'
                            ? 'Choose the record, change what you need, and review it before it is saved.'
                            : 'Add many records at once from an Excel file.'}
                      </p>
                    </div>
                    {canChange && (
                      <div role="group" aria-label="What to do" className="flex rounded-full border border-[color:var(--color-border)] bg-muted p-1">
                        {(
                          [
                            ['Create', 'Add', Plus],
                            ['Update', 'Edit', Pencil],
                            ['Upload', 'Upload', Upload],
                          ] as const
                        ).map(([mode, label, Icon]) => (
                          <button
                            key={mode}
                            type="button"
                            aria-pressed={action === mode}
                            onClick={() => openWrite(mode)}
                            className={`interactive inline-flex h-8 items-center gap-1.5 rounded-full px-3.5 text-sm font-semibold ${action === mode ? 'bg-surface text-[color:var(--color-text)] shadow-card' : 'text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]'}`}
                          >
                            <Icon className="h-3.5 w-3.5" />
                            {label}
                          </button>
                        ))}
                      </div>
                    )}
                    <button type="button" disabled={submitting} onClick={closeForm} aria-label="Close the form" className="interactive grid h-9 w-9 place-items-center rounded-full text-[color:var(--color-text-faint)] hover:bg-muted hover:text-[color:var(--color-text)]">
                      <X className="h-5 w-5" />
                    </button>
                  </div>
                ) : (
                <div className="flex shrink-0 flex-col gap-3 border-b border-[color:var(--color-border)] px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <h2 className="text-sm font-semibold tracking-tight">
                      {action === 'Create'
                        ? `New ${entityNoun(selectedEntity)}`
                        : action === 'Update'
                          ? `Edit ${entityNoun(selectedEntity)}`
                          : `Upload ${entityNoun(selectedEntity)}`}
                    </h2>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {canChange && (
                      <>
                        <Button size="sm" variant={action === 'Create' ? 'strong' : 'secondary'} onClick={() => openWrite('Create')}>
                          <Plus className="h-4 w-4" />
                          Add
                        </Button>
                        <Button size="sm" variant={action === 'Update' ? 'strong' : 'secondary'} onClick={() => openWrite('Update')}>
                          <Pencil className="h-4 w-4" />
                          Edit
                        </Button>
                        <Button size="sm" variant={action === 'Upload' ? 'strong' : 'secondary'} onClick={() => openWrite('Upload')}>
                          <Upload className="h-4 w-4" />
                          Upload
                        </Button>
                      </>
                    )}
                    <Button size="sm" variant="secondary" disabled={submitting} onClick={closeForm}>
                      <X className="h-4 w-4" />
                      Close
                    </Button>
                  </div>
                </div>
                )}
                {message && (
                  <div className="shrink-0 px-5 pt-4">
                    <Alert variant="success" onDismiss={() => setMessage('')}>
                      {message}
                    </Alert>
                  </div>
                )}
                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
                  {action === 'Upload' && (
                    <div className="mx-auto max-w-3xl">
                      <ExcelUploadPanel
                        hideHeader
                        entityName={selectedEntity}
                        mergeKey={currentMeta.merge_key}
                        onInserted={(result) => {
                          refreshPreview()
                          setMessage(
                            `Excel upload finished: ${result.inserted} inserted, ${result.updated ?? 0} updated.`,
                          )
                          closeForm()
                        }}
                      />
                    </div>
                  )}
                  {action && action !== 'Upload' && (
                    <>
                      {action === 'Update' && (
                        <div className="mb-6 flex max-w-xl items-end gap-2">
                          <Field label="Select record" className="min-w-0 flex-1">
                            <SearchSelect
                              value={selectedRecordId}
                              options={recordOptions}
                              placeholder="— Search by name —"
                              onChange={(next) => setSelectedRecordId(next ?? '')}
                            />
                          </Field>
                          {selectedRecordId && (
                            <Button
                              variant="secondary"
                              onClick={() => setHistoryFor({ id: selectedRecordId, label: selectedRecordLabel })}
                            >
                              <History className="h-4 w-4" /> History
                            </Button>
                          )}
                        </div>
                      )}
                      {lockedReason && (
                        <div className="mb-5">
                          <Alert variant="info">{lockedReason}</Alert>
                        </div>
                      )}
                      {followup && action === 'Create' && selectedEntity === followup.entity && (
                        <div className="mb-5 rounded-xl border border-[color:var(--color-border)] bg-muted/60 px-4 py-3 text-sm">
                          <p className="font-medium text-[color:var(--color-text)]">
                            {followup.entity === 'Case' ? 'Creating the case for' : 'Recording the EMD for'} the won opportunity {followup.name} ({followup.code})
                          </p>
                          <p className="t-caption mt-0.5">
                            The opportunity is fixed. {followup.entity === 'Case' ? 'The case name is filled in from it; change it if the site is called something else.' : 'Choose the case it became.'}
                          </p>
                          {followup.entity === 'EMD' && followup.cases.length === 0 && (
                            <div className="mt-2 flex flex-wrap items-center gap-3">
                              <p className="text-warning">An EMD belongs to a case, and this opportunity has none yet.</p>
                              <Button size="sm" variant="secondary" onClick={() => void startFollowup('Case', followup.code)}>
                                Create the case first
                              </Button>
                            </div>
                          )}
                        </div>
                      )}
                      {!lockedReason && (action === 'Create' || selectedRecordId) && (
                        <FillFromText
                          key={`${selectedEntity}-${action}-${selectedRecordId}`}
                          entity={selectedEntity}
                          onFill={(values) => setFormValues((prev) => ({ ...prev, ...values, ...(followup ? { opportunity_code: followup.code } : {}) }))}
                        />
                      )}
                      <fieldset disabled={Boolean(lockedReason)} className="min-w-0 disabled:opacity-70">
                        <EntityForm
                          entityName={selectedEntity}
                          fields={action === 'Create' ? Object.fromEntries(Object.entries(formFields).filter(([, config]) => !config.readonly)) : formFields}
                          values={formValues}
                          hydrateKey={action === 'Update' ? selectedRecordId : ''}
                          onChange={(k, v) => setFormValues((prev) => ({ ...prev, [k]: v }))}
                          lockedFields={
                            followup && action === 'Create' && selectedEntity === followup.entity
                              ? { opportunity_code: 'Fixed: this is for the opportunity that was won.' }
                              : undefined
                          }
                          optionOverrides={
                            followup && action === 'Create' && selectedEntity === 'EMD'
                              ? { case_code: followup.cases }
                              : undefined
                          }
                        />
                      </fieldset>
                      {error && (
                        <div className="mt-5">
                          <Alert variant="error" onDismiss={() => setError('')}>
                            {error}
                          </Alert>
                          {stale && (
                            <Button size="sm" variant="secondary" className="mt-3" onClick={reloadRecord}>
                              <RefreshCw className="h-4 w-4" /> Open it again with the latest values
                            </Button>
                          )}
                        </div>
                      )}
                      {DOCUMENT_KINDS[selectedEntity] && action === 'Update' && selectedRecordId && (
                        <EmployeeDocuments code={selectedRecordId} kind={DOCUMENT_KINDS[selectedEntity]} />
                      )}
                      {DOCUMENT_KINDS[selectedEntity] && action === 'Create' && (
                        <EmployeeDocuments code={null} kind={DOCUMENT_KINDS[selectedEntity]} staged={stagedDocs} onStagedChange={setStagedDocs} />
                      )}
                      {action === 'Update' && selectedRecordId && !lockedReason && (
                        <div className="mt-8 max-w-xl rounded-2xl border border-negative/30 bg-negative-dim p-4">
                          <p className="text-sm font-medium text-negative">Delete this record</p>
                          <p className="mt-1 text-sm text-negative">This cannot be undone.</p>
                          <div className="mt-3">
                            <Checkbox
                              label="I understand this deletion is permanent"
                              checked={confirmDelete}
                              onChange={setConfirmDelete}
                            />
                          </div>
                          <Button
                            variant="danger"
                            size="sm"
                            className="mt-4"
                            loading={submitting}
                            disabled={!confirmDelete}
                            onClick={handleDelete}
                          >
                            Delete record
                          </Button>
                        </div>
                      )}
                    </>
                  )}
                </div>
                {action && action !== 'Upload' && (
                  <div className={`flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-[color:var(--color-border)] px-5 ${lumen ? 'bg-[color:color-mix(in_srgb,var(--orion-surface)_88%,transparent)] py-3.5 backdrop-blur-xl' : 'py-3'}`}>
                    {lumen && (
                      <p className="mr-auto text-xs text-[color:var(--color-text-muted)]">
                        {action === 'Update' && originalValues
                          ? (() => {
                              const count = fieldChanges(currentMeta.form_fields, originalValues, formValues).length
                              return count ? `${count} ${count === 1 ? 'change' : 'changes'} to review` : 'No changes yet'
                            })()
                          : 'You will be asked to confirm before it is saved.'}
                      </p>
                    )}
                    <Button variant="secondary" disabled={submitting} onClick={closeForm}>
                      Cancel
                    </Button>
                    <Button
                      variant="primary"
                      loading={submitting}
                      disabled={
                        action === 'Update' &&
                        (Boolean(lockedReason) ||
                          !selectedRecordId ||
                          !originalValues ||
                          fieldChanges(currentMeta.form_fields, originalValues, formValues).length === 0)
                      }
                      onClick={handleSubmit}
                    >
                      {action === 'Create' ? 'Create record' : 'Save changes'}
                    </Button>
                  </div>
                )}
              </WorkbenchPanel>
            ) : (
              <WorkbenchPanel fill className="gap-3 p-4">
                {canChange ? (
                  <div className="flex shrink-0 flex-wrap gap-2">
                    <Button size="sm" variant="strong" onClick={() => openWrite('Create')}>
                      <Plus className="h-4 w-4" />
                      Add
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => openWrite('Update')}>
                      <Pencil className="h-4 w-4" />
                      Edit
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => openWrite('Upload')}>
                      <Upload className="h-4 w-4" />
                      Upload
                    </Button>
                  </div>
                ) : null}
                {message && (
                  <Alert variant="success" onDismiss={() => setMessage('')}>
                    {message}
                  </Alert>
                )}
                <div className="min-h-0 flex-1">
                  <PreviewRecords
                    fill
                    key={selectedEntity}
                    title={`${selectedEntity} records`}
                    reloadToken={previewTick + generation}
                    load={(limit, query) => api.entityPreview(selectedEntity, limit, query)}
                    download={(limit, query) => api.downloadEntityExport(selectedEntity, limit, query)}
                    values={(column, query, contains) => api.entityValues(selectedEntity, column, query, contains)}
                    onRowClick={openHistoryFromRow}
                    rowHint="Click to see who changed this record"
                  />
                </div>
              </WorkbenchPanel>
            )
          }
          aside={
            formOpen ? (
              <WorkbenchPanel fill className="gap-3 p-3">
                <PreviewRecords
                  fill
                  key={`${selectedEntity}-side`}
                  title="Records"
                  reloadToken={previewTick + generation}
                  load={(limit, query) => api.entityPreview(selectedEntity, limit, query)}
                  download={(limit, query) => api.downloadEntityExport(selectedEntity, limit, query)}
                  values={(column, query, contains) => api.entityValues(selectedEntity, column, query, contains)}
                />
              </WorkbenchPanel>
            ) : undefined
          }
        />
      )}

      <WriteGate
        open={changeIntent && !changeUnlocked}
        title="Change operational data"
        body="You are opening a write workspace on live operational records. Anything you add, change, or delete is real working data. Dashboards and the warehouse stay as they are until someone loads them. Continue only if you intend to edit records."
        confirmLabel="I understand this is sensitive operational data"
        continueLabel="Continue to change records"
        onCancel={() => navigate('/data/orion', { replace: true })}
        onContinue={() => setChangeUnlocked(true)}
      />

      <RecordHistoryModal
        open={historyFor !== null}
        entity={selectedEntity}
        recordId={historyFor?.id ?? ''}
        recordLabel={historyFor?.label ?? ''}
        onClose={() => setHistoryFor(null)}
      />

      <Modal
        open={Boolean(pending)}
        title={
          pending?.kind === 'create'
            ? 'Confirm create'
            : pending?.kind === 'delete'
              ? 'Confirm delete'
              : 'Confirm update'
        }
        onClose={() => !submitting && setPending(null)}
        footer={
          <>
            <Button variant="secondary" disabled={submitting} onClick={() => setPending(null)}>
              Cancel
            </Button>
            <Button
              variant={pending?.kind === 'delete' ? 'danger' : 'strong'}
              loading={submitting}
              onClick={applyPending}
            >
              {pending?.kind === 'create' && pending.duplicates?.length ? 'Save anyway' : 'Yes, proceed'}
            </Button>
          </>
        }
      >
        {pending?.kind === 'create' && (
          <>
            {pending.duplicates && pending.duplicates.length > 0 && (
              <div className="mb-4">
                <Alert variant="warning">
                  <span className="font-medium">This looks like {pending.duplicates.length === 1 ? 'an expense' : 'expenses'} already entered:</span>
                  <ul className="mt-1 list-disc pl-5">
                    {pending.duplicates.map((match) => (
                      <li key={match.expense_code}>{match.note}</li>
                    ))}
                  </ul>
                  <span className="mt-1 block">Same type, case and amount within a week. If it is a different expense, save it anyway.</span>
                </Alert>
              </div>
            )}
            <p className="text-sm leading-relaxed text-[color:var(--color-text-muted)]">
              You are inserting a new{' '}
              <span className="font-medium text-[color:var(--color-text)]">{entityNoun(selectedEntity)}</span> record
              with these values:
            </p>
            <ul className="mt-4 divide-y divide-[color:var(--color-border)] overflow-hidden rounded-xl border border-[color:var(--color-border)]">
              {pending.rows.map((row) => (
                <li key={row.key} className="flex items-start justify-between gap-4 bg-muted/40 px-3 py-3">
                  <p className="text-xs font-medium uppercase tracking-wide text-[color:var(--color-text-faint)]">
                    {row.label}
                  </p>
                  <p className="text-right text-sm font-medium text-[color:var(--color-text)]">{row.value}</p>
                </li>
              ))}
            </ul>
          </>
        )}
        {pending?.kind === 'delete' && (
          <>
            <p className="text-sm leading-relaxed text-[color:var(--color-text-muted)]">
              You are deleting this{' '}
              <span className="font-medium text-[color:var(--color-text)]">{entityNoun(selectedEntity)}</span> record
              {selectedRecordLabel ? (
                <>
                  : <span className="font-medium text-[color:var(--color-text)]">{selectedRecordLabel}</span>
                </>
              ) : null}
              . This cannot be undone.
            </p>
            <ul className="mt-4 divide-y divide-[color:var(--color-border)] overflow-hidden rounded-xl border border-negative/30">
              {pending.rows.map((row) => (
                <li key={row.key} className="flex items-start justify-between gap-4 bg-negative-dim px-3 py-3">
                  <p className="text-xs font-medium uppercase tracking-wide text-[color:var(--color-text-faint)]">
                    {row.label}
                  </p>
                  <p className="text-right text-sm font-medium text-[color:var(--color-text)]">{row.value}</p>
                </li>
              ))}
            </ul>
          </>
        )}
        {pending?.kind === 'update' && (
          <>
            <p className="text-sm leading-relaxed text-[color:var(--color-text-muted)]">
              You are updating this{' '}
              <span className="font-medium text-[color:var(--color-text)]">{entityNoun(selectedEntity)}</span> record
              {selectedRecordLabel ? (
                <>
                  : <span className="font-medium text-[color:var(--color-text)]">{selectedRecordLabel}</span>
                </>
              ) : null}
              . These values will change:
            </p>
            <ul className="mt-4 divide-y divide-[color:var(--color-border)] overflow-hidden rounded-xl border border-[color:var(--color-border)]">
              {pending.rows.map((change) => (
                <li key={change.key} className="bg-muted/40 px-3 py-3">
                  <p className="text-xs font-medium uppercase tracking-wide text-[color:var(--color-text-faint)]">
                    {change.label}
                  </p>
                  <p className="mt-1 text-sm">
                    <span className={lumen ? 'rounded-full bg-negative-dim px-2.5 py-0.5 text-xs text-negative line-through' : 'text-[color:var(--color-text-muted)]'}>{change.fromLabel}</span>
                    <span className="mx-2 text-[color:var(--color-text-faint)]">→</span>
                    <span className={lumen ? 'rounded-full bg-positive-dim px-2.5 py-0.5 text-xs font-semibold text-positive' : 'font-medium text-[color:var(--color-text)]'}>{change.toLabel}</span>
                  </p>
                </li>
              ))}
            </ul>
          </>
        )}
      </Modal>
    </WorkbenchShell>
  )
}
