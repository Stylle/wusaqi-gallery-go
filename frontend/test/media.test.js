import test from 'node:test'
import assert from 'node:assert/strict'
import { prepareMedia, shareUrl } from '../src/media.js'

test('viewing paths are never used as fallback share links', () => {
  const value = prepareMedia({ items: [{ url: '/files/private.png', viewUrl: '/media/files/private.png', viewThumb: null, viewCompressed: null, shareUrls: {} }] })
  assert.equal(value.items[0].url, '/media/files/private.png')
  assert.equal(shareUrl(value.items[0], 'original'), '')
})

test('upload receipts and gallery items preserve only explicit external links', () => {
  const value = prepareMedia({ results: [{ item: { viewUrl: '/media/files/a.png', viewThumb: '/media/thumbs/a.webp', shareUrls: { original: '/files/a.png' } } }] })
  assert.equal(value.results[0].item.thumb, '/media/thumbs/a.webp')
  assert.equal(shareUrl(value.results[0].item, 'original'), '/files/a.png')
  assert.equal(shareUrl(value.results[0].item, 'compressed'), '')
})
