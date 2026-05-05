import axios from 'axios'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL ||
  'https://bismillah-super-trading-terminal-production.up.railway.app'

export const api = axios.create({
  baseURL: BACKEND_URL,
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' }
})

api.interceptors.response.use(
  (res) => res,
  (err) => { console.error('[API]', err?.response?.data || err.message); return Promise.reject(err) }
)

export const checkHealth = () => api.get('/health')
export const runScreener = (mode, filters={}) => api.post('/screener/scan', { mode, filters })
export const analyzeStock = (ticker, mode) => api.post('/analytic/analyze', { ticker, mode })
export const startMonitoring = (data) => api.post('/monitoring/add', data)
export const getMonitoringList = () => api.get('/monitoring/list')
export const removeMonitoring = (ticker) => api.delete(`/monitoring/remove/${ticker}`)
export const getScalpingData = (ticker) => api.get(`/scalping/data/${ticker}`)
export const getWsUrl = (ticker) => {
  const base = BACKEND_URL.replace('https://','wss://').replace('http://','ws://')
  return `${base}/ws/scalping/${ticker}`
}
export default api
