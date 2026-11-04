import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Ban, ChevronLeft, Copy, Download, Pencil, Printer, Send } from 'lucide-react'
import { api } from '../../api/client'
import { money } from '../../billing/billCalc'
import { DEFAULT_FONT } from '../../billing/billFonts'
import { BillDocument, formatDay } from '../../components/billing/BillDocument'
import { BillPayments } from '../../components/billing/BillPayments'
import { CreditNotes } from '../../components/billing/CreditNotes'
import { GstPaid } from '../../components/billing/GstPaid'
import { StatutoryPaid } from '../../components/billing/StatutoryPaid'
import { ShareModal } from '../../components/billing/ShareModal'
import { pdfPath, useLetterheadChoice } from '../../components/billing/letterheadChoice'
import { BillDriveLink } from '../../components/billing/BillDrive'
import { BillFiledIn } from '../../components/billing/BillFiledIn'
import { BillFontPicker } from '../../components/billing/BillFontPicker'
import { PrintSheet, printBill, savedToView } from '../../components/billing/PrintSheet'
import { Alert } from '../../components/ui/Alert'
import { Button } from '../../components/ui/Button'
import { Checkbox, Field, Textarea } from '../../components/ui/Field'
import { Modal } from '../../components/ui/Modal'
import { PdfPreview } from '../../components/ui/PdfPreview'
import { useAuth } from '../../context/AuthContext'
import { useLumen } from '../../lumen/useLumen'
import { BillHero, PaperDesk } from '../../components/billing/lumenBill'
import type { BillVersionRow, SavedBill } from '../../types'

const FIGURE_NAMES = { epf_amount: 'EPFO', esic_amount: 'ESIC', service_amount: 'Service charges', cgst_amount: 'CGST', sgst_amount: 'SGST' } as const

/** The figures of a bill that were entered by hand and differ from what the calculation gives, one sentence each. */
function enteredNotes(bill: SavedBill): string[] {
  const notes: string[] = []
  bill.lines.forEach((line, at) => {
    if (line.manual && line.auto_amount != null && Math.abs(line.amount - line.auto_amount) >= 0.005) {
      notes.push(`Line ${at + 1} (${line.particulars}): ₹ ${money(line.amount)}, the calculation gives ₹ ${money(line.auto_amount)}`)
    }
  })
  for (const [key, name] of Object.entries(FIGURE_NAMES)) {
    const figure = bill.manual_figures?.[key as keyof typeof FIGURE_NAMES]
    if (figure && Math.abs(figure.value - figure.auto) >= 0.005) notes.push(`${name}: ₹ ${money(figure.value)}, the calculation gives ₹ ${money(figure.auto)}`)
  }
  return notes
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-[color:var(--color-text-muted)]">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium text-[color:var(--color-text)]">{children}</dd>
    </div>
  )
}

export function BillViewPage() {
  const { id = '' } = useParams()
  const [search] = useSearchParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const canWrite = Boolean(user?.can_billing_write)
  const isAdmin = user?.role === 'admin'
  const [bill, setBill] = useState<SavedBill | null>(null)
  const [versions, setVersions] = useState<BillVersionRow[]>([])
  /** An earlier version being looked at. Null shows the bill as it stands. */
  const [earlier, setEarlier] = useState<SavedBill | null>(null)
  const [error, setError] = useState('')
  const [cancelling, setCancelling] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [sending, setSending] = useState(false)
  const [companyFont, setCompanyFont] = useState<{ family: string; size: number }>({ family: DEFAULT_FONT.family, size: DEFAULT_FONT.size })
  const [fontBusy, setFontBusy] = useState(false)
  const [onLetterhead, setOnLetterhead] = useLetterheadChoice()
  /** The bill on the letterhead, shown to print from. Null while closed. */
  const [preview, setPreview] = useState<{ blob: Blob | null; error: string } | null>(null)

  useEffect(() => {
    setEarlier(null)
    api
      .bill(id)
      .then(setBill)
      .catch((e: Error) => setError(e.message))
    api
      .billingProfile()
      .then((p) => setCompanyFont({ family: p.font_family ?? DEFAULT_FONT.family, size: p.font_size ?? DEFAULT_FONT.size }))
      .catch(() => undefined) // the picker then names Arial 9 as the company's setting
    api
      .billVersions(id)
      .then((r) => setVersions(r.versions))
      .catch(() => setVersions([]))
  }, [id])

  const cancel = async () => {
    if (!bill) return
    setBusy(true)
    try {
      setBill(await api.cancelBill(bill.id, reason))
      setCancelling(false)
      setReason('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const downloadPdf = async () => {
    if (!bill) return
    setError('')
    try {
      await api.downloadPdf(
        pdfPath(`bills/${encodeURIComponent(bill.id)}/pdf`, onLetterhead),
        `Invoice ${bill.bill_number.replace('/', '-')}.pdf`,
      )
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // On the letterhead the bill is printed from its PDF, which the server draws on the letterhead. Without
  // it, the page on screen is printed as it is.
  const print = () => {
    if (!bill) return
    if (!onLetterhead) {
      printBill(`Invoice ${bill.bill_number.replace('/', '-')}`)
      return
    }
    setPreview({ blob: null, error: '' })
    api
      .pdfBlob(`/billing/bills/${encodeURIComponent(bill.id)}/pdf?letterhead=true`)
      .then((blob) => setPreview({ blob, error: '' }))
      .catch((e: Error) => setPreview({ blob: null, error: e.message }))
  }

  const changeFont = async (next: { family: string; size: string }) => {
    if (!bill) return
    setError('')
    setFontBusy(true)
    try {
      setBill(await api.setBillFont(bill.id, { font_family: next.family || null, font_size: next.size ? Number(next.size) : null }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setFontBusy(false)
    }
  }

  const openVersion = async (versionNo: number) => {
    if (!bill) return
    setError('')
    if (versionNo === bill.version_no) {
      setEarlier(null)
      return
    }
    try {
      setEarlier(await api.billVersion(bill.id, versionNo))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const shown = earlier ?? bill
  const view = shown && savedToView(shown)
  const live = bill && !earlier && bill.status === 'Issued'
  // A bill with money received against it cannot be cancelled; an admin reverses the payments first.
  const nothingReceived = (bill?.revenue?.received ?? 0) === 0

  const factsSection = (
    bill && (
      <section className="rounded-xl border border-[color:var(--color-border)] bg-surface px-4 py-3">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 lg:grid-cols-4">
          <Fact label="Case">{shown?.case_name ?? 'Not tagged'}</Fact>
          <Fact label="Client">{shown?.client_name ?? shown?.legacy_client_ledger ?? 'Not set'}</Fact>
          <Fact label="Version">
            {shown?.version_no} of {bill.version_no}
          </Fact>
          <Fact label="GST">
            <GstPaid bill={bill} canWrite={Boolean(canWrite && live)} onChange={setBill} />
          </Fact>
          <Fact label="EPFO and ESIC">
            <StatutoryPaid bill={bill} canWrite={Boolean(canWrite && live)} onChange={setBill} />
          </Fact>
        </dl>
      </section>
    )
  )

  const paymentsPane = (
    bill && !earlier && (
      <BillPayments bill={bill} canWrite={canWrite} isAdmin={isAdmin} onChange={setBill} />
    )
  )

  const creditPane = (
    bill && !earlier && <CreditNotes bill={bill} canWrite={canWrite} isAdmin={isAdmin} onChange={setBill} />
  )

  const letterheadPane = (
    bill && !earlier && (
      <section className="rounded-xl border border-[color:var(--color-border)] bg-surface px-4 py-3">
        <Checkbox label="Use the company letterhead" checked={onLetterhead} onChange={setOnLetterhead} />
        <p className="mt-1 pl-[26px] text-xs text-[color:var(--color-text-muted)]">
          {onLetterhead
            ? 'Print, Download PDF and Send put this bill on the letterhead. The company name, address and registration numbers typed at the top of the bill below are left off, because the letterhead carries them.'
            : 'Print, Download PDF and Send use the bill as shown below, with its own typed heading.'}
        </p>
      </section>
    )
  )

  const filedPane = (
    bill && !earlier && <BillFiledIn billCode={bill.id} canChange={Boolean(user?.can_documents_write)} refreshKey={bill.version_no} />
  )

  const drivePane = (
    bill && !earlier && <BillDriveLink billCode={bill.id} canChange={Boolean(user?.can_documents_write && canWrite)} refreshKey={bill.version_no} />
  )

  const fontPane = (
    bill && !earlier && (
      <section className="rounded-xl border border-[color:var(--color-border)] bg-surface px-4 py-3">
        <p className="text-sm font-semibold text-[color:var(--color-text)]">Text on the bill</p>
        <p className="mb-3 mt-1 text-xs text-[color:var(--color-text-muted)]">
          {canWrite
            ? 'Choose a larger size or another typeface. It applies to what you see, print, download and send, and it does not make a new version of the bill.'
            : 'The typeface and size this bill is printed in.'}
        </p>
        <BillFontPicker
          family={bill.font_family ?? ''}
          size={bill.font_size ? String(bill.font_size) : ''}
          company={companyFont}
          disabled={!canWrite || fontBusy}
          onChange={changeFont}
        />
      </section>
    )
  )

  const paperPane = (
    <div className="overflow-x-auto pb-2">{view && <BillDocument bill={view} />}</div>
  )

  const versionsPane = (
    bill && versions.length > 1 && (
      <section className="rounded-xl border border-[color:var(--color-border)] bg-surface">
        <header className="border-b border-[color:var(--color-border)] px-4 py-3">
          <h3 className="t-h3 text-[color:var(--color-text)]">Version history</h3>
          <p className="mt-0.5 text-xs text-[color:var(--color-text-muted)]">
            Every edit keeps the version it replaced. Open one to see the bill as it was.
          </p>
        </header>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[color:var(--color-text-muted)]">
                <th className="px-4 py-2 font-medium">Version</th>
                <th className="px-4 py-2 font-medium">Saved on</th>
                <th className="px-4 py-2 font-medium">Saved by</th>
                <th className="px-4 py-2 font-medium">What changed</th>
                <th className="px-4 py-2 text-right font-medium">Grand total</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {versions.map((row) => {
                const open = row.version_no === (shown?.version_no ?? bill.version_no)
                return (
                  <tr key={row.version_no} className="border-t border-[color:var(--color-border)]">
                    <td className="px-4 py-2 font-medium text-[color:var(--color-text)]">
                      {row.version_no}
                      {row.is_current && (
                        <span className="ml-2 text-xs font-normal text-[color:var(--color-text-muted)]">current</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-[color:var(--color-text)]">{formatDay(row.saved_timestamp)}</td>
                    <td className="px-4 py-2 text-[color:var(--color-text)]">{row.saved_by ?? ''}</td>
                    <td className="px-4 py-2 text-[color:var(--color-text-muted)]">
                      {row.reason ?? (row.version_no === 1 ? 'Bill issued' : '')}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-[color:var(--color-text)]">
                      ₹ {money(row.grand_total)}
                    </td>
                    <td className="px-4 py-2 text-right">
                      {open ? (
                        <span className="text-xs text-[color:var(--color-text-muted)]">Showing</span>
                      ) : (
                        <Button variant="ghost" size="sm" onClick={() => openVersion(row.version_no)}>
                          View
                        </Button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    )
  )

  const lumen = useLumen()

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          to="/utility/billing"
          className="inline-flex items-center gap-1 text-sm font-medium text-[color:var(--color-text-muted)] hover:text-[color:var(--color-text)]"
        >
          <ChevronLeft className="h-4 w-4" /> Bills
        </Link>
        {bill && !earlier && (
          <div className="flex flex-wrap items-center gap-2">
            {canWrite && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => navigate(`/utility/billing/new?from=${encodeURIComponent(bill.id)}`)}
              >
                <Copy className="h-4 w-4" /> Copy as new bill
              </Button>
            )}
            {canWrite && live && (
              <>
                <Button variant="secondary" size="sm" onClick={() => navigate(`/utility/billing/${bill.id}/edit`)}>
                  <Pencil className="h-4 w-4" /> Edit bill
                </Button>
                {nothingReceived && (
                  <Button variant="secondary" size="sm" onClick={() => setCancelling(true)}>
                    <Ban className="h-4 w-4" /> Cancel bill
                  </Button>
                )}
              </>
            )}
            <Button variant="secondary" size="sm" onClick={downloadPdf}>
              <Download className="h-4 w-4" /> Download PDF
            </Button>
            {canWrite && live && (
              <Button variant="secondary" size="sm" onClick={() => setSending(true)}>
                <Send className="h-4 w-4" /> Send
              </Button>
            )}
            <Button onClick={print}>
              <Printer className="h-4 w-4" /> Print
            </Button>
          </div>
        )}
      </div>

      {error && <Alert variant="error">{error}</Alert>}
      {bill && search.get('saved') === 'edit' && !earlier && (
        <Alert variant="success">
          Bill {bill.bill_number} is saved as version {bill.version_no}. The version it replaced is in the version
          history below.
        </Alert>
      )}
      {bill && search.get('saved') && search.get('saved') !== 'edit' && (
        <Alert variant="success">
          Bill {bill.bill_number} is issued. Send it to the client, download it as a PDF, or print it.
        </Alert>
      )}
      {bill?.status === 'Cancelled' && (
        <Alert variant="error">
          This bill was cancelled{bill.cancelled_reason ? `: ${bill.cancelled_reason}` : ''}. Its number stays on record.
        </Alert>
      )}
      {bill && !earlier && enteredNotes(bill).length > 0 && (
        <Alert variant="info">
          <span>
            Some figures on this bill were entered by hand and do not match the calculation:
            <ul className="mt-1 list-disc pl-5">
              {enteredNotes(bill).map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </span>
        </Alert>
      )}
      {bill && !bill.case_code && bill.status === 'Issued' && (
        <Alert variant="info">
          This bill is not tagged to a case. It was raised before bills were tagged to cases
          {bill.legacy_client_ledger ? `, for ${bill.legacy_client_ledger}` : ''}.
          {canWrite ? ' Edit the bill to choose its case.' : ''}
        </Alert>
      )}
      {earlier && bill && (
        <Alert variant="info">
          <span>
            You are looking at version {earlier.version_no} of {bill.version_no}, which has been replaced. It cannot be
            printed or edited.{' '}
            <button type="button" className="font-semibold underline" onClick={() => setEarlier(null)}>
              Back to the current version
            </button>
          </span>
        </Alert>
      )}

      {lumen && bill && (
        <BillHero
          number={shown?.bill_number ?? bill.bill_number}
          status={bill.status === 'Cancelled' ? 'Cancelled' : (bill.revenue?.remaining ?? 1) <= 0.005 && (bill.revenue?.received ?? 0) > 0 ? 'Paid in full' : (bill.revenue?.received ?? 0) > 0 ? 'Part paid' : 'Awaiting payment'}
          who={shown?.client_name ?? shown?.legacy_client_ledger ?? shown?.party_name ?? 'Client not set'}
          where={shown?.case_name ?? 'Not tagged to a case'}
          version={`Version ${shown?.version_no} of ${bill.version_no}`}
          grandTotal={bill.grand_total}
          settled={bill.grand_total - (bill.revenue?.remaining ?? bill.grand_total)}
          received={(bill.revenue?.received ?? 0) - (bill.revenue?.deducted ?? 0)}
          heldBack={bill.revenue?.deducted ?? 0}
          credited={bill.revenue?.credited ?? 0}
          remaining={bill.revenue?.remaining ?? bill.grand_total}
          cancelled={bill.status === 'Cancelled'}
        />
      )}

      {lumen && bill && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
          <div className="min-w-0 space-y-5">
            {view && <PaperDesk><BillDocument bill={view} /></PaperDesk>}
            {versionsPane}
          </div>
          <div className="lumen-aside min-w-0 space-y-4">
            <section className="panel !p-4" aria-label="GST">
              <p className="eyebrow mb-2">GST</p>
              <GstPaid bill={bill} canWrite={Boolean(canWrite && live)} onChange={setBill} />
            </section>
            <section className="panel !p-4" aria-label="EPFO and ESIC">
              <p className="eyebrow mb-2">EPFO and ESIC</p>
              <StatutoryPaid bill={bill} canWrite={Boolean(canWrite && live)} onChange={setBill} />
            </section>
            {paymentsPane}
            {creditPane}
            {letterheadPane}
            {filedPane}
            {drivePane}
            {fontPane}
          </div>
        </div>
      )}

      {!lumen && factsSection}

      {!lumen && paymentsPane}

      {!lumen && creditPane}

      {!lumen && letterheadPane}

      {!lumen && filedPane}

      {!lumen && drivePane}

      {!lumen && fontPane}

      {!lumen && paperPane}
      {view && !earlier && <PrintSheet bill={view} />}
      {!lumen && versionsPane}

      {bill && live && (
        <ShareModal
          open={sending}
          title={`Send bill ${bill.bill_number}`}
          target={`bills/${encodeURIComponent(bill.id)}`}
          pdfPath={`bills/${encodeURIComponent(bill.id)}/pdf`}
          pdfName={`Invoice ${bill.bill_number.replace('/', '-')}.pdf`}
          letterhead={onLetterhead}
          onClose={() => setSending(false)}
        />
      )}

      {bill && (
        <PdfPreview
          open={preview !== null}
          title={`Bill ${bill.bill_number} on the letterhead`}
          blob={preview?.blob ?? null}
          error={preview?.error}
          filename={`Invoice ${bill.bill_number.replace('/', '-')}.pdf`}
          onClose={() => setPreview(null)}
        />
      )}

      <Modal
        open={cancelling}
        title={`Cancel bill ${bill?.bill_number ?? ''}`}
        onClose={() => setCancelling(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setCancelling(false)}>
              Keep bill
            </Button>
            <Button variant="danger" onClick={cancel} loading={busy} disabled={!reason.trim()}>
              Cancel this bill
            </Button>
          </>
        }
      >
        <p className="mb-3 text-sm text-[color:var(--color-text-muted)]">
          A cancelled bill cannot be reopened and its number is not reused. To correct a bill and keep its number, edit
          it instead.
        </p>
        <Field label="Reason" required>
          <Textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} />
        </Field>
      </Modal>
    </div>
  )
}
