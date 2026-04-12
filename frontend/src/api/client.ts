import axios from 'axios'
import { API_BASE } from './config'

const api = axios.create({
  baseURL: `${API_BASE}/api`,
})

export default api
