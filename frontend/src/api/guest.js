import { auth, tasks as tasksApi, workspaces as workspacesApi } from './client.js'

const GUEST_KEY = 'collabspace.guest'

/**
 * Guest mode is a development convenience for looking at the UI without
 * signing up. It is on automatically in `npm run dev`; a production build has
 * to opt in with VITE_ENABLE_GUEST=true.
 */
export function isGuestEnabled() {
  return import.meta.env.DEV || import.meta.env.VITE_ENABLE_GUEST === 'true'
}

function randomHex(bytes = 6) {
  const buffer = new Uint8Array(bytes)
  crypto.getRandomValues(buffer)
  return Array.from(buffer, (b) => b.toString(16).padStart(2, '0')).join('')
}

export function getStoredGuest() {
  try {
    const raw = localStorage.getItem(GUEST_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function storeGuest(credentials) {
  localStorage.setItem(GUEST_KEY, JSON.stringify(credentials))
}

export function clearGuest() {
  localStorage.removeItem(GUEST_KEY)
}

/**
 * Each browser gets its own throwaway account rather than a shared one with
 * known credentials, so a guest session is a private sandbox and there is no
 * fixed login for anyone who finds the deployment.
 */
export function newGuestCredentials() {
  return {
    email: `guest-${randomHex()}@example.com`,
    password: `guest-${randomHex(12)}`,
    guest: true,
  }
}

/** Gives a fresh guest something to look at instead of an empty dashboard. */
export async function seedGuestData() {
  const workspace = await workspacesApi.create('Demo Workspace')
  const samples = [
    { title: 'Design the landing page', status: 'TODO', description: 'Hero, features, pricing.' },
    { title: 'Set up CI pipeline', status: 'TODO' },
    { title: 'Build authentication', status: 'IN_PROGRESS', description: 'JWT + bcrypt.' },
    { title: 'Project scaffolding', status: 'DONE' },
  ]
  // Sequential so positions come back in the order listed above.
  for (const sample of samples) {
    await tasksApi.create(workspace.id, sample)
  }
  return workspace
}

/** Registers a brand-new guest, logs it in, and seeds a demo board. */
export async function createGuestAccount() {
  const credentials = newGuestCredentials()
  await auth.register(credentials.email, credentials.password)
  storeGuest(credentials)
  return credentials
}
