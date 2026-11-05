export interface Rle {
  size: [number, number]
  counts: number[]
}

// COCO 列优先（Fortran order）RLE -> row-major Uint8Array
export function decodeRle(rle: Rle): Uint8Array {
  const [h, w] = rle.size
  const mask = new Uint8Array(h * w)
  let k = 0
  let v = 0
  for (const c of rle.counts) {
    for (let j = 0; j < c; j++) {
      const row = k % h
      const col = Math.floor(k / h)
      mask[row * w + col] = v
      k++
    }
    v = 1 - v
  }
  return mask
}

// row-major Uint8Array -> COCO 列优先 counts
export function encodeRle(mask: Uint8Array, h: number, w: number): number[] {
  const counts: number[] = []
  let last = 0
  let run = 0
  for (let col = 0; col < w; col++) {
    for (let row = 0; row < h; row++) {
      const v = mask[row * w + col] ? 1 : 0
      if (v === last) {
        run++
      } else {
        counts.push(run)
        last = v
        run = 1
      }
    }
  }
  counts.push(run)
  return counts
}

export function emptyMask(h: number, w: number): Uint8Array {
  return new Uint8Array(h * w)
}