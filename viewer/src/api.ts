import { ReportData } from './types'

export function extractViewToken(): string {
  const parts = window.location.pathname.split('/')
  return parts[parts.length - 1] || ''
}

export async function fetchReportData(viewToken: string): Promise<ReportData> {
  const res = await fetch(`/api/report/${viewToken}`)
  if (!res.ok) {
    if (res.status === 404) throw new Error('NOT_FOUND')
    throw new Error('NETWORK_ERROR')
  }
  return res.json()
}
