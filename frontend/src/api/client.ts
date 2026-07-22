export const API_BASE_URL = 'http://127.0.0.1:8000'

export interface HealthResponse {
  status: string
  database_status: string
  deepseek_configured: boolean
  table_count: number
}

export interface KnowledgeSourceItem {
  knowledge_type: 'schema' | 'metric' | 'trusted_sql' | 'historical_qa'
  source_id: string
  title: string
  score: number
}

export interface ChatChart {
  type?: string
  x?: string
  y?: string
  reason?: string
  [key: string]: unknown
}

export interface ChatResponse {
  question: string
  session_id: string
  data_source_id: number | null
  sql: string
  sql_explanation: string
  data: Record<string, unknown>[]
  chart: ChatChart
  insights: Record<string, string>[]
  knowledge_sources: KnowledgeSourceItem[]
  trusted_answer: boolean
  answer: string
  error: string | null
  error_code: string | null
}

export interface QueryLogItem {
  id: number
  question: string
  sql: string
  trusted_answer: boolean
  chart_type: string
  row_count: number
  error: string | null
  error_code: string | null
  feedback: string | null
  feedback_note: string | null
  duration_ms: number
  created_at: string
}

export interface QueryStatsResponse {
  total_queries: number
  success_queries: number
  failed_queries: number
  trusted_answer_queries: number
  average_duration_ms: number
  chart_type_counts: Record<string, number>
  feedback_counts: Record<string, number>
  error_code_counts: Record<string, number>
  top_questions: { question: string; count: number }[]
}

export interface QueryLogListResponse {
  items: QueryLogItem[]
}

export function getHealth() {
  return request<HealthResponse>('/health')
}

export function askQuestion(question: string, sessionId?: string) {
  return request<ChatResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ question, session_id: sessionId || undefined }),
  })
}

export function getQueryStats() {
  return request<QueryStatsResponse>('/api/query-stats')
}

export function getQueryLogs(limit = 10) {
  return request<QueryLogListResponse>(`/api/query-logs?limit=${limit}`)
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  })

  if (!response.ok) {
    let message = `HTTP ${response.status}`
    try {
      const payload = await response.json()
      message = payload.detail || message
    } catch {
      // keep default message
    }
    throw new Error(message)
  }

  return response.json() as Promise<T>
}
