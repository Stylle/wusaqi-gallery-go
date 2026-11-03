// Rendering always uses the internal viewing path. Only shareUrls may be
// copied as an external link; an absent entry must never fall back to url.
export function prepareMedia(value) {
  if (!value || typeof value !== 'object') return value
  if (Array.isArray(value)) return value.map(prepareMedia)
  if (value.viewUrl) return { ...value, url: value.viewUrl, thumb: value.viewThumb, compressed: value.viewCompressed }
  for (const key of Object.keys(value)) value[key] = prepareMedia(value[key])
  return value
}

export function shareUrl(item, variant) {
  return item?.shareUrls?.[variant] || ''
}
