import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export const api = axios.create({ baseURL })

export async function getHealth() {
  const { data } = await api.get('/health')
  return data
}
