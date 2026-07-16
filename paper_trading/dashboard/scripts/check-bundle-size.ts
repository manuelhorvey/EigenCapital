/** Bundle size check for CI.
 *  Runs after `npm run build` to verify total gzipped JS size stays under
 *  a reasonable threshold (~200KB gzip for a React trading dashboard with
 *  Recharts, react-query, zod, and lucide-react).
 *
 *  Usage: node scripts/check-bundle-size.mjs
 *  Expected to run after `vite build` populates dist/assets/.
 *
 *  Increase the threshold if intentional dependencies are added.
 */

import { readFileSync, readdirSync, statSync } from 'fs'
import { createGzip, gzipSync } from 'zlib'
import { join, extname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))

const LIMIT_KB = 220

const distAssets = join(__dirname, '..', 'dist', 'assets')

let totalGzip = 0
const files: { name: string; gzipKb: number }[] = []

if (exists(distAssets)) {
  for (const f of readdirSync(distAssets)) {
    const ext = extname(f)
    if (ext !== '.js' && ext !== '.css') continue
    const fp = join(distAssets, f)
    const raw = readFileSync(fp)
    const gzipped = gzipSync(raw)
    const kb = gzipped.length / 1024
    totalGzip += kb
    files.push({ name: f, gzipKb: Math.round(kb * 10) / 10 })
  }
}

files.sort((a, b) => b.gzipKb - a.gzipKb)
for (const f of files) {
  const bar = '█'.repeat(Math.min(Math.round(f.gzipKb), 60))
  console.log(`  ${f.name.padEnd(40)} ${String(f.gzipKb.toFixed(1)).padStart(6)} KB  ${bar}`)
}

console.log(`\n  Total gzip: ${totalGzip.toFixed(1)} KB  (limit: ${LIMIT_KB} KB)`)

if (totalGzip > LIMIT_KB) {
  console.error(`\n  ❌ Bundle size ${totalGzip.toFixed(1)} KB exceeds limit of ${LIMIT_KB} KB`)
  process.exit(1)
} else {
  console.log(`  ✅ Bundle size within limit\n`)
}

function exists(p: string): boolean {
  try {
    statSync(p)
    return true
  } catch {
    return false
  }
}
