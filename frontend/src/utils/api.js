import axios from 'axios'

const BACKEND_URL = 'https://bismillah-super-trading-terminal-production.up.railway.app'

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
export const runScreener = (mode, filters={}) => api.post('/api/screener/run', { mode, filters })
export const analyzeStock = (ticker, mode) => api.post('/api/analytic/analyze', { ticker, mode })
export const startMonitoring = (data) => api.post('/api/monitoring/start', data)
export const getMonitoringList = () => api.get('/api/monitoring/list')
export const removeMonitoring = (ticker) => api.delete(`/api/monitoring/remove/${ticker}`)
export const getScalpingData = (ticker) => api.get(`/api/scalping/data/${ticker}`)
export const getWsUrl = (ticker) => {
  return `wss://bismillah-super-trading-terminal-production.up.railway.app/ws/scalping/${ticker}`
}
export default api
