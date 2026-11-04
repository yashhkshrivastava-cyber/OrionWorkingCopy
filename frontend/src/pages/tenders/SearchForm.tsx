import { useEffect, useRef, useState } from 'react'
import { api, tendersApi } from '../../api/client'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Checkbox, Field, Input, Select, Switch } from '../../components/ui/Field'
import { Modal } from '../../components/ui/Modal'
import { MoneyInput } from '../../components/ui/MoneyInput'
import { MultiSelect } from '../../components/ui/MultiSelect'
import type { TenderBidKind, TenderSearch, TenderSearchInput, TenderSource } from '../../types'

/** Tender types people here usually look for; any other word can be typed. */
const TYPE_SUGGESTIONS = ['Security', 'Manpower outsourcing', 'Housekeeping', 'Facility management', 'Cleaning', 'Driver', 'Data entry', 'Gardening']
const LAKH = 100000
/** The most a search may name (the server holds the same limits): a state's every district fits. */
const MAX_TYPES = 20
const MAX_CITIES = 100
/** Each city is a separate question to GeM, asked a couple of seconds apart: past this a check takes a few minutes. */
const SLOW_AFTER = 25

function lakhs(value: number | null): string {
  return value == null ? '' : String(Math.round((value / LAKH) * 100) / 100)
}

function rupees(text: string): number | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  const number = Number(trimmed)
  return Number.isFinite(number) ? Math.round(number * LAKH) : NaN
}

/** Add or change a saved search. */
export function SearchForm({
  portal,
  open,
  search,
  onClose,
  onSaved,
}: {
  /** The portal the search belongs to: it never looks on the other. */
  portal: TenderSource
  open: boolean
  search: TenderSearch | null
  onClose: () => void
  onSaved: (saved: TenderSearch) => void
}) {
  const [name, setName] = useState('')
  const [types, setTypes] = useState<string[]>([])
  const [cities, setCities] = useState<string[]>([])
  const [kind, setKind] = useState<TenderBidKind>('service')
  const [minLakh, setMinLakh] = useState('')
  const [maxLakh, setMaxLakh] = useState('')
  const [unpriced, setUnpriced] = useState(true)
  const [active, setActive] = useState(true)
  const [states, setStates] = useState<string[]>([])
  const [state, setState] = useState('Madhya Pradesh')
  const [stateCities, setStateCities] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const errorBox = useRef<HTMLDivElement>(null)

  // The form can be taller than the dialog: bring a refusal into view instead of leaving it above the fold.
  useEffect(() => {
    if (error) errorBox.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [error])

  useEffect(() => {
    if (!open) return
    setName(search?.name ?? '')
    setTypes(search?.tender_types ?? [])
    setCities(search?.cities ?? [])
    setKind(search?.bid_kind ?? 'service')
    setMinLakh(lakhs(search?.min_value ?? null))
    setMaxLakh(lakhs(search?.max_value ?? null))
    setUnpriced(search?.include_unpriced ?? true)
    setActive(search?.is_active ?? true)
    setError(null)
  }, [open, search])

  useEffect(() => {
    if (!open || states.length) return
    api.states().then((found) => setStates(found.states)).catch(() => setStates([]))
  }, [open, states.length])

  useEffect(() => {
    if (!open || !state) return
    let live = true
    api.cities(state).then((found) => live && setStateCities(found.cities)).catch(() => live && setStateCities([]))
    return () => {
      live = false
    }
  }, [open, state])

  const save = async () => {
    const min = rupees(minLakh)
    const max = rupees(maxLakh)
    if (Number.isNaN(min) || Number.isNaN(max)) return setError('Values are numbers of lakhs, for example 10 or 2.5.')
    const input: TenderSearchInput = {
      name,
      tender_types: types,
      cities,
      bid_kind: kind,
      min_value: min,
      max_value: max,
      include_unpriced: unpriced,
      is_active: active,
      portal,
    }
    setBusy(true)
    setError(null)
    try {
      onSaved(search ? await tendersApi.saveSearch(search.search_id, input) : await tendersApi.createSearch(input))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The search could not be saved.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      title={`${search ? 'Change' : 'New'} ${portal === 'mptenders' ? 'MP Tenders' : 'GeM'} search`}
      onClose={onClose}
      size="xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={save} loading={busy}>
            {search ? 'Save search' : 'Add search'}
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <div ref={errorBox} hidden={!error}>
          {error && <Alert variant="error">{error}</Alert>}
        </div>
        <Field label="Name" required>
          <Input value={name} maxLength={80} placeholder="Security and manpower in Gwalior" onChange={(event) => setName(event.target.value)} />
        </Field>
        <Field
          label="Tender types"
          hint={portal === 'mptenders'
            ? 'Words in the tender\'s title, work description or category, such as Security or Housekeeping. At least one is needed on MP Tenders.'
            : 'Words in the bid\'s GeM category, such as Security or Manpower outsourcing. A bid matches if it has any of them. Leave empty for every type.'}
        >
          <MultiSelect
            label="Tender types"
            values={types}
            onChange={setTypes}
            options={TYPE_SUGGESTIONS}
            noun={['type', 'types']}
            placeholder="Choose tender types"
            allowCustom
            max={MAX_TYPES}
          />
        </Field>
        <div className="space-y-3">
          <Field label="Cities" hint="Where the work must be. Orion reads it from each bid's consignee address. Leave empty for anywhere.">
            <div className="space-y-2">
              <Select aria-label="State to choose cities from" value={state} onChange={(event) => setState(event.target.value)}>
                {(states.length ? states : [state]).map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </Select>
              <MultiSelect
                label={`Cities of ${state}`}
                values={cities}
                onChange={setCities}
                options={stateCities}
                noun={['city', 'cities']}
                placeholder={`Choose cities of ${state}`}
                searchPlaceholder="Search a city, or type one that is not listed and press Enter"
                allowCustom
                max={MAX_CITIES}
                actions={[
                  {
                    label: stateCities.length ? `All ${stateCities.length} cities of ${state}` : `All cities of ${state}`,
                    disabled: !stateCities.length,
                    title: `Choose every city of ${state}`,
                    onClick: ({ add }) => add(stateCities),
                  },
                ]}
              />
            </div>
          </Field>
          {cities.length > SLOW_AFTER && (
            <p className="t-caption">
              {cities.length} cities are {cities.length} separate questions to {portal === 'mptenders' ? 'the portal' : 'GeM'}, asked a few seconds apart, so a check of this search takes several minutes.
            </p>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={portal === 'mptenders' ? 'Tender category' : 'Kind of bid'}>
            <Select value={kind} onChange={(event) => setKind(event.target.value as TenderBidKind)}>
              <option value="service">Services</option>
              <option value="product">{portal === 'mptenders' ? 'Goods' : 'Products'}</option>
              {portal === 'mptenders' && <option value="works">Works</option>}
              <option value="all">{portal === 'mptenders' ? 'All categories' : 'All bids'}</option>
            </Select>
          </Field>
          <Field label="Minimum value (₹ lakh)">
            <MoneyInput value={minLakh} decimals={4} scale={LAKH} placeholder="Any" onChange={setMinLakh} />
          </Field>
          <Field label="Maximum value (₹ lakh)">
            <MoneyInput value={maxLakh} decimals={4} scale={LAKH} placeholder="Any" onChange={setMaxLakh} />
          </Field>
        </div>
        <Checkbox
          label="Include bids that do not state a value (many state only the EMD)"
          checked={unpriced}
          onChange={setUnpriced}
        />
        <Switch
          label="Check this search"
          hint="Orion checks active searches by itself every few hours, and when you press Check now."
          checked={active}
          onChange={setActive}
        />
        {search && <p className="t-caption">Saving clears this search's New list; it is filled again under the new terms at the next check. Shortlisted and dismissed bids stay.</p>}
      </div>
    </Modal>
  )
}
