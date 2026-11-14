// Browser storage may be unavailable in embedded or privacy-restricted browsers.
export function readStorage(name, key, fallback = '') {
  try { return globalThis[name].getItem(key) ?? fallback } catch { return fallback }
}
export function writeStorage(name, key, value) {
  try { globalThis[name].setItem(key, value); return true } catch { return false }
}
export function removeStorage(name, key) {
  try { globalThis[name].removeItem(key); return true } catch { return false }
}
