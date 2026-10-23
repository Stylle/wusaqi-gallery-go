// Assign by known aspect ratio: appending a batch never moves existing cards
// between columns, unlike balanced CSS multicolumn layout.
export function columnsFor(width, viewport, size) {
  const gap = viewport <= 768 ? 8 : 12
  const sizes = viewport <= 560 ? { s: 88, m: 132, l: width }
    : viewport <= 768 ? { s: 100, m: 148, l: 260 }
      : { s: 130, m: 200, l: 320 }
  return Math.max(1, Math.floor((width + gap) / ((sizes[size] || sizes.m) + gap)))
}

export function masonryColumns(items, count, width, gap) {
  const columns = Array.from({ length: count }, () => [])
  const heights = Array(count).fill(0)
  const columnWidth = Math.max(1, (width - gap * (count - 1)) / count)
  for (const item of items) {
    const index = heights.indexOf(Math.min(...heights))
    columns[index].push(item)
    heights[index] += columnWidth * Math.max(1, Number(item.height)) / Math.max(1, Number(item.width)) + gap
  }
  return columns
}
