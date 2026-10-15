// Light/dark theme. index.html sets <html data-theme> before the app loads,
// from the same storage key and rules as here, so the first paint is already
// in the right theme. These helpers keep it in sync afterwards.

export const THEME_KEY = 'collabspace.theme'

export function currentTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'
}

/** The user's explicit choice, or null if they have never picked one. */
export function savedTheme() {
  try {
    const value = localStorage.getItem(THEME_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null // storage blocked (private mode, strict settings)
  }
}

export function applyTheme(theme, { save = false } = {}) {
  document.documentElement.setAttribute('data-theme', theme)
  if (!save) return
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Not persisted; the choice still applies for this page view.
  }
}
