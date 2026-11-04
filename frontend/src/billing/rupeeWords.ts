const ONES = [
  'Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten',
  'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen',
]
const TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

function underHundred(n: number): string {
  if (n < 20) return ONES[n]
  return TENS[Math.floor(n / 10)] + (n % 10 ? ` ${ONES[n % 10]}` : '')
}

function underThousand(n: number): string {
  const hundreds = Math.floor(n / 100)
  const rest = n % 100
  return [hundreds ? `${ONES[hundreds]} Hundred` : '', rest ? underHundred(rest) : ''].filter(Boolean).join(' ')
}

/** Whole rupees in the Indian system: lakh and crore, not million. 919149 -> "Nine Lakh Nineteen Thousand ..." */
export function rupeesInWords(amount: number): string {
  const rupees = Math.round(amount)
  if (rupees === 0) return 'Zero Rupees Only'
  if (rupees === 1) return 'One Rupee Only'
  const parts: string[] = []
  let rest = rupees
  const crore = Math.floor(rest / 10_000_000)
  rest %= 10_000_000
  const lakh = Math.floor(rest / 100_000)
  rest %= 100_000
  const thousand = Math.floor(rest / 1000)
  rest %= 1000
  if (crore) parts.push(`${crore >= 100 ? rupeesInWords(crore).replace(' Rupees Only', '') : underHundred(crore)} Crore`)
  if (lakh) parts.push(`${underHundred(lakh)} Lakh`)
  if (thousand) parts.push(`${underHundred(thousand)} Thousand`)
  if (rest) parts.push(underThousand(rest))
  return `${parts.join(' ')} Rupees Only`
}

/** A whole number of rupees, one or more, in the Indian system, without the word "Rupees". */
function wholeInWords(n: bigint): string {
  const parts: string[] = []
  const crore = n / 10_000_000n
  let rest = n % 10_000_000n
  const lakh = Number(rest / 100_000n)
  rest %= 100_000n
  const thousand = Number(rest / 1000n)
  const hundreds = Number(rest % 1000n)
  if (crore) parts.push(`${crore >= 100n ? wholeInWords(crore) : underHundred(Number(crore))} Crore`)
  if (lakh) parts.push(`${underHundred(lakh)} Lakh`)
  if (thousand) parts.push(`${underHundred(thousand)} Thousand`)
  if (hundreds) parts.push(underThousand(hundreds))
  return parts.join(' ')
}

/**
 * An amount with its paise in words, the way a cheque is written: "One Thousand Two Hundred Fifty Rupees and Seventy Five Paise Only".
 * Whole numbers of any size (a bigint), so nothing is rounded however many crore.
 */
export function amountInWords(rupees: bigint, paise = 0): string {
  const rupeeWords = rupees > 0n ? `${wholeInWords(rupees)} ${rupees === 1n ? 'Rupee' : 'Rupees'}` : ''
  const paiseWords = paise > 0 ? `${underHundred(paise)} ${paise === 1 ? 'Paisa' : 'Paise'}` : ''
  if (!rupeeWords && !paiseWords) return 'Zero Rupees Only'
  return `${[rupeeWords, paiseWords].filter(Boolean).join(' and ')} Only`
}
