/**
 * Preparing an attached image for the model.
 *
 * Two different things are made from one file, because they answer to different
 * constraints:
 *
 *   `data`  goes to the bridge and on to the model. Claude downsamples anything
 *           wider than ~1568px, so sending more pixels costs upload time on a
 *           phone connection and buys no detail.
 *   `thumb` is what the transcript keeps. Conversations live in localStorage,
 *           which is a handful of megabytes for the whole origin, so the full
 *           image must never be what gets stored - a couple of screenshots
 *           would evict the rest of the history.
 *
 * Both are produced here rather than at the call site so that the size rules
 * stay in one place.
 */

export const ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']
export const MAX_IMAGES = 8

const MAX_EDGE = 1568
const THUMB_EDGE = 320
// Guard against someone dropping a 100MB raw photo in: read it, and the tab
// spends seconds on a file that is about to be shrunk anyway.
const MAX_SOURCE_BYTES = 24 * 1024 * 1024

export function isSupportedImage(file) {
  return Boolean(file) && ACCEPTED_TYPES.includes(file.type)
}

/** btoa() takes a string, and a big array blows the argument limit - so chunk. */
function toBase64(buffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  const CHUNK = 0x8000
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK))
  }
  return btoa(binary)
}

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('Could not read the file.'))
    reader.readAsDataURL(file)
  })
}

/**
 * Decode to something drawable.
 *
 * createImageBitmap is the fast path, but Safari has shipped it late and
 * partially, and this app is opened from phones - so an <img> fallback is not
 * optional.
 */
async function decode(file) {
  if (typeof createImageBitmap === 'function') {
    try {
      return await createImageBitmap(file)
    } catch {
      /* fall through to the <img> path */
    }
  }
  const url = URL.createObjectURL(file)
  try {
    return await new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = () => reject(new Error('That file is not an image this browser can read.'))
      img.src = url
    })
  } finally {
    // Revoking immediately is safe: decoding is done by the time we get here.
    URL.revokeObjectURL(url)
  }
}

function sizeWithin(width, height, edge) {
  const scale = Math.min(1, edge / Math.max(width, height))
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
    scaled: scale < 1,
  }
}

function draw(source, width, height, { opaque } = {}) {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  // JPEG has no alpha: without a backdrop, transparent pixels come out black,
  // which turns a screenshot with rounded corners into a framed mess.
  if (opaque) {
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, width, height)
  }
  ctx.drawImage(source, 0, 0, width, height)
  return canvas
}

function canvasToBlob(canvas, type, quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('Could not encode the image.'))),
      type,
      quality
    )
  })
}

/**
 * One attachment, ready to send and to render.
 *
 * Returns `{ id, name, mediaType, data, thumb, width, height, bytes }` where
 * `data` is raw base64 (no data: prefix - the bridge wants the payload, not the
 * envelope) and `thumb` is a small data URL for display.
 */
export async function prepareImage(file) {
  if (!isSupportedImage(file)) {
    throw new Error(`${file?.name || 'That file'} is not a PNG, JPEG, GIF or WebP.`)
  }
  if (file.size > MAX_SOURCE_BYTES) {
    throw new Error(`${file.name} is larger than 24MB.`)
  }

  const bitmap = await decode(file)
  const width = bitmap.width || bitmap.naturalWidth
  const height = bitmap.height || bitmap.naturalHeight

  const full = sizeWithin(width, height, MAX_EDGE)
  const small = sizeWithin(width, height, THUMB_EDGE)

  let mediaType = file.type
  let data

  // An animated GIF loses its animation the moment it touches a canvas, and the
  // model only ever sees one frame regardless - so an unscaled GIF is passed
  // through untouched unless it is big enough that shrinking is worth the lost
  // frames.
  const passthrough = file.type === 'image/gif' && !full.scaled
  if (passthrough) {
    data = toBase64(await file.arrayBuffer())
  } else {
    // PNG survives as PNG: screenshots are the common case here and re-encoding
    // text to JPEG smears it. Everything else goes to JPEG, which is far
    // smaller for photographs.
    const asPng = file.type === 'image/png'
    mediaType = asPng ? 'image/png' : 'image/jpeg'
    const canvas = draw(bitmap, full.width, full.height, { opaque: !asPng })
    const blob = await canvasToBlob(canvas, mediaType, asPng ? undefined : 0.85)
    data = toBase64(await blob.arrayBuffer())
  }

  const thumbCanvas = draw(bitmap, small.width, small.height, { opaque: true })
  const thumb = thumbCanvas.toDataURL('image/jpeg', 0.6)

  if (typeof bitmap.close === 'function') bitmap.close()

  return {
    id: `img${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`,
    name: file.name || 'image',
    mediaType,
    data,
    thumb,
    width: full.width,
    height: full.height,
    // Base64 inflates by 4/3; this is the decoded size, which is what the
    // bridge's limits are expressed in.
    bytes: Math.round((data.length * 3) / 4),
  }
}

/** Pulls images out of a paste or drop, ignoring everything else. */
export function imageFilesFrom(dataTransfer) {
  const files = []
  for (const item of dataTransfer?.files || []) {
    if (isSupportedImage(item)) files.push(item)
  }
  if (files.length) return files
  // A screenshot pasted from the clipboard arrives as an item, not a file.
  for (const item of dataTransfer?.items || []) {
    if (item.kind !== 'file') continue
    const file = item.getAsFile()
    if (isSupportedImage(file)) files.push(file)
  }
  return files
}

/** What actually travels to the bridge: no thumbnails, no filenames. */
export function toWirePayload(attachments) {
  return attachments.map((a) => ({ mediaType: a.mediaType, data: a.data }))
}
