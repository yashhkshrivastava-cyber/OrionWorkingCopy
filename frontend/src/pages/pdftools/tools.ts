import {
  ArrowUpDown,
  Droplets,
  FileCog,
  FileImage,
  FileMinus,
  FileOutput,
  FileText,
  Hash,
  ImagePlus,
  Lock,
  LockOpen,
  Merge,
  Minimize2,
  RotateCw,
  Shrink,
  Split,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import { plural } from './format'

/*
 * What each PDF tool is, what it needs and what it asks. The option names are the ones backend/app/pdf_tools.py reads
 * (a test checks every tool here exists there and the other way round). One page (PdfToolPage) draws any of them.
 */

export type Choice = { id: string; label: string }

type Common = { key: string; label: string; hint?: string; showIf?: (values: Values) => boolean }

export type FieldSpec =
  | (Common & { kind: 'text'; placeholder?: string; max?: number; required?: boolean })
  | (Common & { kind: 'pages'; placeholder?: string; required?: boolean })
  | (Common & { kind: 'number'; min: number; max: number })
  | (Common & { kind: 'choice'; options: Choice[] })
  | (Common & { kind: 'check' })
  | (Common & { kind: 'password'; required?: boolean })

export type Values = Record<string, string | boolean>

export type ToolGroup = 'Organise' | 'Convert' | 'Optimise and protect' | 'Edit and mark'

export interface ToolDef {
  id: string
  title: string
  blurb: string
  icon: LucideIcon
  group: ToolGroup
  /** pdfs: two or more PDFs, in an order. pdf: one. images: pictures, in an order. */
  accept: 'pdfs' | 'pdf' | 'images'
  fields: FieldSpec[]
  defaults: Values
  /** The button, given how many files are chosen. */
  action: (count: number) => string
  /** What is still missing, in words, or null when it can go. */
  missing?: (values: Values) => string | null
  /** The details of the PDF chosen fill these fields (Edit details). */
  prefillDetails?: boolean
}

const PAGES_ALL = 'All pages'
const HOW_TO_WRITE_PAGES = 'Write pages like 1-3, 5, 8- (a range, one page, from page 8 to the end). last means the final page; odd and even work too.'

const pages = (key = 'pages', label = 'Which pages', required = false): FieldSpec => ({
  kind: 'pages',
  key,
  label,
  placeholder: required ? 'for example 1-3, 5, 8-' : PAGES_ALL,
  hint: required ? HOW_TO_WRITE_PAGES : `Leave empty for every page. ${HOW_TO_WRITE_PAGES}`,
  required,
})


export const TOOLS: ToolDef[] = [
  {
    id: 'merge',
    title: 'Merge PDFs',
    blurb: 'Join several PDFs into one, in the order you choose.',
    icon: Merge,
    group: 'Organise',
    accept: 'pdfs',
    fields: [{ kind: 'check', key: 'bookmarks', label: 'Add a bookmark for each file', hint: 'The PDF viewer shows each file by name in its side panel.' }],
    defaults: { bookmarks: true },
    action: (count) => (count >= 2 ? `Merge ${count} PDFs` : 'Merge PDFs'),
  },
  {
    id: 'split',
    title: 'Split a PDF',
    blurb: 'Cut one PDF into several files, delivered together as a ZIP.',
    icon: Split,
    group: 'Organise',
    accept: 'pdf',
    fields: [
      {
        kind: 'choice',
        key: 'mode',
        label: 'Split by',
        options: [
          { id: 'ranges', label: 'Page ranges' },
          { id: 'every', label: 'Every N pages' },
          { id: 'single', label: 'One page each' },
        ],
      },
      {
        kind: 'pages',
        key: 'ranges',
        label: 'The parts',
        placeholder: 'for example 1-3, 4-6, 7-',
        hint: 'Each part, separated by commas, becomes its own PDF: 1-3, 4, 6- makes three files.',
        required: true,
        showIf: (v) => v.mode === 'ranges',
      },
      { kind: 'number', key: 'every', label: 'Pages in each file', min: 1, max: 1500, showIf: (v) => v.mode === 'every' },
    ],
    defaults: { mode: 'ranges', ranges: '', every: '2' },
    action: () => 'Split the PDF',
    missing: (v) => (v.mode === 'ranges' && !String(v.ranges).trim() ? 'Write the parts to cut it into.' : null),
  },
  {
    id: 'extract',
    title: 'Extract pages',
    blurb: 'Keep only the pages you name, as a new PDF.',
    icon: FileOutput,
    group: 'Organise',
    accept: 'pdf',
    fields: [pages('pages', 'Pages to keep', true)],
    defaults: { pages: '' },
    action: () => 'Extract the pages',
    missing: (v) => (String(v.pages).trim() ? null : 'Write the pages to keep.'),
  },
  {
    id: 'remove',
    title: 'Remove pages',
    blurb: 'Take pages out of a PDF and keep the rest.',
    icon: FileMinus,
    group: 'Organise',
    accept: 'pdf',
    fields: [pages('pages', 'Pages to remove', true)],
    defaults: { pages: '' },
    action: () => 'Remove the pages',
    missing: (v) => (String(v.pages).trim() ? null : 'Write the pages to remove.'),
  },
  {
    id: 'organize',
    title: 'Reorder pages',
    blurb: 'Put the pages in a new order, repeat one, or add blank pages.',
    icon: ArrowUpDown,
    group: 'Organise',
    accept: 'pdf',
    fields: [
      {
        kind: 'text',
        key: 'order',
        label: 'The new order',
        placeholder: 'for example 3, 1, blank, 4-9',
        hint: 'List the pages as they should come. A page can come twice, and blank adds an empty page. Or leave this empty and reverse the whole PDF below.',
      },
      { kind: 'check', key: 'reverse', label: 'Reverse the whole PDF', hint: 'The last page becomes the first. Used only when the order above is empty.' },
    ],
    defaults: { order: '', reverse: false },
    action: () => 'Reorder the pages',
    missing: (v) => (String(v.order).trim() || v.reverse ? null : 'Write the new order, or choose Reverse.'),
  },
  {
    id: 'rotate',
    title: 'Rotate pages',
    blurb: 'Turn all the pages, or only some, a quarter or half turn.',
    icon: RotateCw,
    group: 'Organise',
    accept: 'pdf',
    fields: [
      {
        kind: 'choice',
        key: 'angle',
        label: 'Turn clockwise',
        options: [
          { id: '90', label: '90° right' },
          { id: '180', label: 'Upside down' },
          { id: '270', label: '90° left' },
        ],
      },
      pages(),
    ],
    defaults: { angle: '90', pages: '' },
    action: () => 'Rotate',
  },
  {
    id: 'resize',
    title: 'Resize pages',
    blurb: 'Fit every page onto A4, A3, A5, Letter or Legal paper.',
    icon: Minimize2,
    group: 'Organise',
    accept: 'pdf',
    fields: [
      {
        kind: 'choice',
        key: 'size',
        label: 'Paper size',
        options: [
          { id: 'a4', label: 'A4' },
          { id: 'a3', label: 'A3' },
          { id: 'a5', label: 'A5' },
          { id: 'letter', label: 'Letter' },
          { id: 'legal', label: 'Legal' },
        ],
        hint: 'Each page is scaled to fit, kept in proportion and centred. Landscape pages go on landscape paper. Links and form fields are not kept.',
      },
    ],
    defaults: { size: 'a4' },
    action: () => 'Resize the pages',
  },
  {
    id: 'images-to-pdf',
    title: 'Pictures to PDF',
    blurb: 'Turn photos or scans (JPG, PNG, HEIC and more) into a PDF, one to a page.',
    icon: ImagePlus,
    group: 'Convert',
    accept: 'images',
    fields: [
      {
        kind: 'choice',
        key: 'size',
        label: 'Page size',
        options: [
          { id: 'a4', label: 'A4' },
          { id: 'letter', label: 'Letter' },
          { id: 'fit', label: 'Same as the picture' },
        ],
      },
      {
        kind: 'choice',
        key: 'orientation',
        label: 'Direction',
        options: [
          { id: 'auto', label: 'Automatic' },
          { id: 'portrait', label: 'Upright' },
          { id: 'landscape', label: 'Sideways' },
        ],
        showIf: (v) => v.size !== 'fit',
        hint: 'Automatic puts a wide picture on a sideways page.',
      },
      { kind: 'number', key: 'margin_mm', label: 'Margin (mm)', min: 0, max: 40, showIf: (v) => v.size !== 'fit' },
    ],
    defaults: { size: 'a4', orientation: 'auto', margin_mm: '10' },
    action: (count) => `Make a PDF of ${plural(count, 'picture', 'pictures')}`,
  },
  {
    id: 'extract-images',
    title: 'Pictures from a PDF',
    blurb: 'Take the photos and scans out of a PDF, as a ZIP of image files.',
    icon: FileImage,
    group: 'Convert',
    accept: 'pdf',
    fields: [
      {
        kind: 'number',
        key: 'min_px',
        label: 'Skip pictures smaller than (pixels)',
        min: 1,
        max: 5000,
        hint: 'Small ones are usually logos and lines. Only pictures inside the PDF are taken: a page drawn as text is not a picture.',
      },
    ],
    defaults: { min_px: '100' },
    action: () => 'Get the pictures',
  },
  {
    id: 'text',
    title: 'Read the text',
    blurb: 'Copy the words out of a PDF into a plain text file.',
    icon: FileText,
    group: 'Convert',
    accept: 'pdf',
    fields: [pages()],
    defaults: { pages: '' },
    action: () => 'Get the text',
  },
  {
    id: 'compress',
    title: 'Compress',
    blurb: 'Make a PDF smaller to email or upload, keeping it readable.',
    icon: Shrink,
    group: 'Optimise and protect',
    accept: 'pdf',
    fields: [
      {
        kind: 'choice',
        key: 'level',
        label: 'How much',
        options: [
          { id: 'light', label: 'Light' },
          { id: 'recommended', label: 'Recommended' },
          { id: 'strong', label: 'Strong' },
        ],
        hint: 'Light tidies the file without touching the pictures. Recommended and Strong also make the pictures inside lighter, which is where most of the size is.',
      },
    ],
    defaults: { level: 'recommended' },
    action: () => 'Compress',
  },
  {
    id: 'repair',
    title: 'Repair',
    blurb: 'Mend a PDF that will not open properly, as far as it can be read.',
    icon: Wrench,
    group: 'Optimise and protect',
    accept: 'pdf',
    fields: [],
    defaults: {},
    action: () => 'Repair the PDF',
  },
  {
    id: 'protect',
    title: 'Lock with a password',
    blurb: 'Protect a PDF so that anyone who opens it needs a password.',
    icon: Lock,
    group: 'Optimise and protect',
    accept: 'pdf',
    fields: [
      { kind: 'password', key: 'new_password', label: 'Password to open it', required: true, hint: 'Orion does not keep it and cannot recover it. Keep it safe.' },
      { kind: 'password', key: 'owner_password', label: 'Separate password to change the rules (optional)' },
      { kind: 'check', key: 'allow_print', label: 'Allow printing' },
      { kind: 'check', key: 'allow_copy', label: 'Allow copying text' },
      { kind: 'check', key: 'allow_edit', label: 'Allow editing' },
    ],
    defaults: { new_password: '', owner_password: '', allow_print: true, allow_copy: true, allow_edit: false },
    action: () => 'Lock the PDF',
    missing: (v) => (String(v.new_password).length >= 4 ? null : 'Choose a password of at least 4 characters.'),
  },
  {
    id: 'unlock',
    title: 'Unlock',
    blurb: 'Take the password off a PDF you know the password of.',
    icon: LockOpen,
    group: 'Optimise and protect',
    accept: 'pdf',
    fields: [],
    defaults: {},
    action: () => 'Unlock the PDF',
  },
  {
    id: 'watermark',
    title: 'Watermark',
    blurb: 'Put words such as CONFIDENTIAL or DRAFT across the pages.',
    icon: Droplets,
    group: 'Edit and mark',
    accept: 'pdf',
    fields: [
      { kind: 'text', key: 'text', label: 'The words', placeholder: 'CONFIDENTIAL', max: 60, required: true },
      {
        kind: 'choice',
        key: 'layout',
        label: 'Where',
        options: [
          { id: 'center', label: 'One across the middle' },
          { id: 'tiled', label: 'Repeated over the page' },
        ],
      },
      {
        kind: 'choice',
        key: 'colour',
        label: 'Colour',
        options: [
          { id: 'grey', label: 'Grey' },
          { id: 'red', label: 'Red' },
          { id: 'blue', label: 'Blue' },
          { id: 'green', label: 'Green' },
          { id: 'black', label: 'Black' },
        ],
      },
      { kind: 'number', key: 'opacity', label: 'Strength (%)', min: 5, max: 100, hint: 'Lower is fainter.' },
      { kind: 'number', key: 'size', label: 'Size', min: 10, max: 200 },
      { kind: 'number', key: 'angle', label: 'Slant (degrees)', min: 0, max: 90, hint: '0 is straight across, 45 is diagonal.' },
      pages(),
    ],
    defaults: { text: '', layout: 'center', colour: 'grey', opacity: '25', size: '64', angle: '45', pages: '' },
    action: () => 'Add the watermark',
    missing: (v) => (String(v.text).trim() ? null : 'Write the words for the watermark.'),
  },
  {
    id: 'page-numbers',
    title: 'Page numbers',
    blurb: 'Number the pages at a corner, or the middle of the top or bottom.',
    icon: Hash,
    group: 'Edit and mark',
    accept: 'pdf',
    fields: [
      {
        kind: 'choice',
        key: 'position',
        label: 'Where',
        options: [
          { id: 'bottom-center', label: 'Bottom middle' },
          { id: 'bottom-right', label: 'Bottom right' },
          { id: 'bottom-left', label: 'Bottom left' },
          { id: 'top-center', label: 'Top middle' },
          { id: 'top-right', label: 'Top right' },
          { id: 'top-left', label: 'Top left' },
        ],
      },
      {
        kind: 'choice',
        key: 'format',
        label: 'Looks like',
        options: [
          { id: 'page_n_of_total', label: 'Page 2 of 9' },
          { id: 'page_n', label: 'Page 2' },
          { id: 'n_of_total', label: '2 / 9' },
          { id: 'n', label: '2' },
        ],
      },
      { kind: 'number', key: 'start', label: 'First page is numbered', min: 0, max: 9999 },
      { kind: 'number', key: 'size', label: 'Size', min: 6, max: 36 },
      { kind: 'number', key: 'margin_mm', label: 'Distance from the edge (mm)', min: 3, max: 40 },
      { kind: 'check', key: 'skip_first', label: 'Leave the first page without a number', hint: 'For a cover page. The numbering still counts it.' },
      pages(),
    ],
    defaults: { position: 'bottom-center', format: 'page_n_of_total', start: '1', size: '10', margin_mm: '10', skip_first: false, pages: '' },
    action: () => 'Number the pages',
  },
  {
    id: 'metadata',
    title: 'Edit details',
    blurb: 'Change the title, author, subject and keywords inside a PDF, or clear them.',
    icon: FileCog,
    group: 'Edit and mark',
    accept: 'pdf',
    prefillDetails: true,
    fields: [
      { kind: 'text', key: 'title', label: 'Title', max: 500 },
      { kind: 'text', key: 'author', label: 'Author', max: 500 },
      { kind: 'text', key: 'subject', label: 'Subject', max: 500 },
      { kind: 'text', key: 'keywords', label: 'Keywords', max: 500 },
      { kind: 'check', key: 'clear', label: 'Clear every detail instead', hint: 'Takes out who made the file and with what, before you share it.' },
    ],
    defaults: { title: '', author: '', subject: '', keywords: '', clear: false },
    action: () => 'Save the details',
  },
]

export const TOOL_BY_ID = new Map(TOOLS.map((tool) => [tool.id, tool]))

export const GROUPS: ToolGroup[] = ['Organise', 'Convert', 'Optimise and protect', 'Edit and mark']
