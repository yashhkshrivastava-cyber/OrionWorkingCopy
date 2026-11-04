/**
 * What a new document starts with. These are starting text only: once chosen, everything can be changed.
 * They are written here, not kept in the database, so a new installation has them and nothing has to be seeded.
 */

const COMPANY = 'Prakash Security Service & Worker Contractor'
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

export function today(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${String(now.getDate()).padStart(2, '0')}`
}

/** 07 October 2026, as a letter is dated. */
export function longDate(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  return year ? `${String(day).padStart(2, '0')} ${MONTHS[month - 1]} ${year}` : ''
}

const signature = `<p><br></p><p>Yours faithfully,</p><p>For <b>${COMPANY.replace('&', '&amp;')}</b></p><p><br></p><p><br></p><p>Authorised Signatory</p>`

export type TemplateId = 'blank' | 'letter' | 'quotation' | 'certificate'

export const TEMPLATES: { id: TemplateId; label: string; hint: string; title: string; body: (date: string) => string }[] = [
  {
    id: 'letter',
    label: 'Letter',
    hint: 'Date, reference, addressee, subject and signature laid out, ready to fill in.',
    title: 'Letter',
    body: (date) =>
      `<p>Ref. No.: </p><p style="text-align:right">Date: ${longDate(date)}</p>` +
      '<p>To,</p><p>The ____________,</p><p>____________</p><p>____________</p><p><br></p>' +
      '<p><b>Subject: ____________</b></p><p><br></p><p>Dear Sir/Madam,</p>' +
      '<p>____________</p><p><br></p><p>Thanking you,</p>' +
      signature,
  },
  {
    id: 'quotation',
    label: 'Quotation',
    hint: 'A rates table with terms below it.',
    title: 'Quotation',
    body: (date) =>
      '<h2 style="text-align:center">QUOTATION</h2>' +
      `<p>Ref. No.: </p><p style="text-align:right">Date: ${longDate(date)}</p>` +
      '<p>To,</p><p>____________</p><p>____________</p><p><br></p>' +
      '<p><b>Subject: Quotation for ____________</b></p>' +
      '<p>Dear Sir/Madam,</p><p>With reference to your enquiry, we are pleased to quote our rates as under:</p>' +
      '<table><tbody>' +
      '<tr><th>S. No.</th><th>Particulars</th><th style="text-align:right">Qty</th><th style="text-align:right">Rate (Rs.)</th><th style="text-align:right">Amount (Rs.)</th></tr>' +
      '<tr><td>1</td><td><br></td><td style="text-align:right"><br></td><td style="text-align:right"><br></td><td style="text-align:right"><br></td></tr>' +
      '<tr><td>2</td><td><br></td><td style="text-align:right"><br></td><td style="text-align:right"><br></td><td style="text-align:right"><br></td></tr>' +
      '<tr><td>3</td><td><br></td><td style="text-align:right"><br></td><td style="text-align:right"><br></td><td style="text-align:right"><br></td></tr>' +
      '</tbody></table>' +
      '<p><b>Terms and conditions</b></p><ol><li>GST extra as applicable.</li><li>This quotation is valid for 30 days from its date.</li><li>Payment within 7 days of the bill.</li></ol>' +
      signature,
  },
  {
    id: 'certificate',
    label: 'Certificate',
    hint: 'A centred "To whom it may concern" with place, date and signature.',
    title: 'Certificate',
    body: (date) =>
      '<p><br></p><h2 style="text-align:center">TO WHOM IT MAY CONCERN</h2><p><br></p>' +
      '<p style="text-align:justify">This is to certify that ____________</p><p><br></p>' +
      `<p>Place: Gwalior</p><p>Date: ${longDate(date)}</p>` +
      `<p><br></p><p style="text-align:right">For <b>${COMPANY.replace('&', '&amp;')}</b></p><p><br></p><p><br></p><p style="text-align:right">Authorised Signatory</p>`,
  },
  {
    id: 'blank',
    label: 'Blank page',
    hint: 'Only the letterhead. Type or paste anything.',
    title: '',
    body: () => '<p><br></p>',
  },
]

export const templateById = (id: string | null) => TEMPLATES.find((template) => template.id === id) ?? TEMPLATES[TEMPLATES.length - 1]
