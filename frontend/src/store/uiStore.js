import { create } from 'zustand'

const THEME_STORAGE_KEY = 'mingcang-theme'
const LEGACY_THEME_STORAGE_KEY = 'stock-sage-theme'

/**
 * Global UI state store (zustand).
 *
 * Owns the theme preference that was previously prop-drilled from App
 * down through Navbar and into StockDetailPage.  A single subscription
 * point means any component can read or toggle the theme without
 * receiving it as a prop.
 */
export const useUiStore = create((set) => ({
  /** 'dark' | 'light' */
  theme:
    (typeof localStorage !== 'undefined' &&
      (localStorage.getItem(THEME_STORAGE_KEY) ||
        localStorage.getItem(LEGACY_THEME_STORAGE_KEY))) ||
    'dark',

  /** Toggle between 'dark' and 'light', persist to localStorage. */
  toggleTheme: () =>
    set((state) => {
      const next = state.theme === 'dark' ? 'light' : 'dark'
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem(THEME_STORAGE_KEY, next)
        localStorage.removeItem(LEGACY_THEME_STORAGE_KEY)
      }
      return { theme: next }
    }),

  /** Directly set theme value (used by App's initial DOM sync). */
  setTheme: (value) =>
    set(() => {
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem(THEME_STORAGE_KEY, value)
        localStorage.removeItem(LEGACY_THEME_STORAGE_KEY)
      }
      return { theme: value }
    }),
}))
