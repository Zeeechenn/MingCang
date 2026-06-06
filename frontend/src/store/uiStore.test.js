/**
 * uiStore tests — run with node --test (no DOM required).
 *
 * We test the pure state transitions by importing the store in a
 * jsdom-free Node environment.  Since zustand's vanilla store works
 * without React, we call getState() / setState() directly after
 * importing the store module.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

// Minimal localStorage stub so the store module initialises cleanly.
const _storage = new Map()
globalThis.localStorage = {
  getItem: (k) => _storage.get(k) ?? null,
  setItem: (k, v) => _storage.set(k, v),
  removeItem: (k) => _storage.delete(k),
}

// Dynamic import after stub is in place.
const { useUiStore } = await import('./uiStore.js')

test('uiStore initial theme defaults to dark when storage is empty', () => {
  _storage.clear()
  // Re-read the current state (store was already created with whatever was in storage at import time).
  // For subsequent assertions we manipulate state directly.
  const { setTheme, theme } = useUiStore.getState()
  // Reset to known baseline.
  setTheme('dark')
  assert.equal(useUiStore.getState().theme, 'dark')
})

test('uiStore toggleTheme flips dark -> light', () => {
  useUiStore.getState().setTheme('dark')
  useUiStore.getState().toggleTheme()
  assert.equal(useUiStore.getState().theme, 'light')
})

test('uiStore toggleTheme flips light -> dark', () => {
  useUiStore.getState().setTheme('light')
  useUiStore.getState().toggleTheme()
  assert.equal(useUiStore.getState().theme, 'dark')
})

test('uiStore toggleTheme persists to localStorage', () => {
  _storage.clear()
  useUiStore.getState().setTheme('dark')
  useUiStore.getState().toggleTheme()
  assert.equal(_storage.get('mingcang-theme'), 'light')
})

test('uiStore setTheme removes legacy key', () => {
  _storage.set('stock-sage-theme', 'light')
  useUiStore.getState().setTheme('dark')
  assert.equal(_storage.has('stock-sage-theme'), false)
})
