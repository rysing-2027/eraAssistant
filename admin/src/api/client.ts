import axios from 'axios'

const api = axios.create({
  baseURL: '/api/admin',
  withCredentials: true, // Send cookies
  headers: {
    'Content-Type': 'application/json'
  }
})

// Response interceptor for 401
api.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401) {
      // Redirect to login
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

// Auth API
export const authApi = {
  login: (username: string, password: string) =>
    api.post('/login', { username, password }),

  logout: () =>
    api.post('/logout'),

  me: () =>
    api.get('/me')
}

// Records API
export const recordsApi = {
  list: (params?: { status?: string; page?: number; page_size?: number }) =>
    api.get('/records', { params }),

  get: (id: number) =>
    api.get(`/records/${id}`),

  stats: () =>
    api.get('/records/stats/summary')
}

// Product Knowledge API
export const productKnowledgeApi = {
  list: () =>
    api.get('/product-knowledge'),

  create: (data: any) =>
    api.post('/product-knowledge', data),

  update: (id: number, data: any) =>
    api.put(`/product-knowledge/${id}`, data),

  delete: (id: number) =>
    api.delete(`/product-knowledge/${id}`)
}

// Evaluation Criteria API
export const evaluationCriteriaApi = {
  list: () =>
    api.get('/evaluation-criteria'),

  create: (data: any) =>
    api.post('/evaluation-criteria', data),

  update: (id: number, data: any) =>
    api.put(`/evaluation-criteria/${id}`, data),

  delete: (id: number) =>
    api.delete(`/evaluation-criteria/${id}`)
}

// Email Template API
export const emailTemplateApi = {
  list: () =>
    api.get('/email-templates'),

  create: (data: any) =>
    api.post('/email-templates', data),

  update: (id: number, data: any) =>
    api.put(`/email-templates/${id}`, data),

  delete: (id: number) =>
    api.delete(`/email-templates/${id}`)
}

export default api