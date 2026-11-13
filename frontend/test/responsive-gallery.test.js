import assert from 'node:assert/strict'
import test from 'node:test'
import { columnsFor } from '../src/layout.js'

test('phone gallery retains its existing compact, medium and full-width card layouts', () => {
  for (const [viewport, small] of [[320, 3], [375, 3], [414, 4]]) {
    const width = viewport - 24
    assert.deepEqual(['s', 'm', 'l'].map(size => columnsFor(width, viewport, size)), [small, 2, 1])
  }
})

test('wide desktop cards grow with available width while density choices remain distinct', () => {
  const narrowWidth = 1094, wideWidth = 2432
  const narrow = columnsFor(narrowWidth, 1150, 'l')
  const wide = columnsFor(wideWidth, 2560, 'l')
  assert.ok(wideWidth / wide > 1.5 * narrowWidth / narrow)
  const counts = ['s', 'm', 'l'].map(size => columnsFor(wideWidth, 2560, size))
  assert.ok(counts[0] > counts[1] && counts[1] > counts[2])
  assert.ok(counts.every(count => count >= 1))
})
