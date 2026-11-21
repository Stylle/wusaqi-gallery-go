// Rendering uses internal viewing paths; copying uses explicit authorized URLs.
// Never fall back to a cookie-only viewing URL or a login-session credential.
export function prepareMedia(value) {
  if (!value || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(prepareMedia)
  if (value.viewUrl) return { ...value, url: value.viewUrl, thumb: value.viewThumb, compressed: value.viewCompressed }
  for (const key of Object.keys(value)) value[key] = prepareMedia(value[key])
  return value
}

export function shareUrl(item, variant, authenticated = false) {
  return (authenticated ? item?.personalUrls?.[variant] : '') || item?.shareUrls?.[variant] || ''
}
