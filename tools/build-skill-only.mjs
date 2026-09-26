// Build the script-free variant of the project-work-log skill.
//
//   node tools/build-skill-only.mjs              # write dist/skill-only/
//   node tools/build-skill-only.mjs --check      # exit 1 if dist/ differs
//   node tools/build-skill-only.mjs --dry-run    # print the plan, write nothing
//   node tools/build-skill-only.mjs --out DIR    # write somewhere else
//
// The source of truth is the hand-written `skill-only/` tree next to this
// file's parent. `dist/` is a build artifact: it exists only so the three files
// can be copied into another harness as a ready-made bundle, and it is
// deliberately NOT listed in package.json's `files`.
//
// Paths resolve from this script's own location, never from cwd — the same
// reason tests/_pkg.mjs probes instead of assuming (this script runs both from
// the package root and from anywhere else).
//
// Node builtins only, and no package.json is required: this directory is not a
// package.
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync }
  from 'node:fs'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

/** This file's directory (`<pkg>/tools`). */
const HERE = dirname(fileURLToPath(import.meta.url))
/** The package root, one level up. */
const ROOT = resolve(HERE, '..')

const SOURCE_REL = 'skill-only/project-work-log'
const DEFAULT_OUT_REL = 'dist/skill-only/project-work-log'

/** The whole variant: exactly these three files, no more. */
const FILES = [
  'SKILL.md',
  'references/conventions.md',
  'references/templates.md',
]

/** Compare and copy on LF, so a CRLF checkout is not reported as drift. */
const normalize = (text) => text.replace(/\r\n?/g, '\n')

/** POSIX-shaped path for display, so output looks the same on every platform. */
const shown = (absolute) => relative(ROOT, absolute).split(sep).join('/')

function fail(message) {
  console.error(`error: ${message}`)
  process.exit(2)
}

function parseArgs(argv) {
  const options = { check: false, dryRun: false, out: null }
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    if (arg === '--check') options.check = true
    else if (arg === '--dry-run') options.dryRun = true
    else if (arg === '--out') {
      const value = argv[i + 1]
      if (value === undefined || value.startsWith('--')) fail('--out needs a directory')
      options.out = resolve(value)
      i += 1
    } else {
      fail(`unknown argument: ${arg}\nusage: node tools/build-skill-only.mjs [--check] [--dry-run] [--out DIR]`)
    }
  }
  if (options.check && options.dryRun) fail('--check and --dry-run are mutually exclusive')
  return options
}

/** Read the source tree, asserting it is exactly the three expected files. */
function readSource(sourceDir) {
  if (!existsSync(sourceDir) || !statSync(sourceDir).isDirectory()) {
    fail(`the source tree is missing: ${shown(sourceDir)}`)
  }

  const found = []
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name)
      if (statSync(path).isDirectory()) walk(path)
      else found.push(relative(sourceDir, path).split(sep).join('/'))
    }
  }
  walk(sourceDir)

  const unexpected = found.filter((f) => !FILES.includes(f))
  const missing = FILES.filter((f) => !found.includes(f))
  if (missing.length > 0) fail(`source is missing ${missing.join(', ')}`)
  if (unexpected.length > 0) {
    fail(`source carries files the variant must not ship: ${unexpected.join(', ')}`)
  }

  return FILES.map((rel) => ({ rel, text: normalize(readFileSync(join(sourceDir, rel), 'utf8')) }))
}

/** What is currently in the output tree, keyed the same way. */
function readOutput(outDir) {
  if (!existsSync(outDir)) return null
  const state = new Map()
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name)
      if (statSync(path).isDirectory()) walk(path)
      else state.set(relative(outDir, path).split(sep).join('/'), normalize(readFileSync(path, 'utf8')))
    }
  }
  walk(outDir)
  return state
}

function diff(files, outDir) {
  const current = readOutput(outDir)
  if (current === null) return { fresh: true, stale: [], extra: [], missing: [] }

  const stale = []
  const missing = []
  for (const { rel, text } of files) {
    if (!current.has(rel)) missing.push(rel)
    else if (current.get(rel) !== text) stale.push(rel)
  }
  const names = files.map((f) => f.rel)
  const extra = [...current.keys()].filter((rel) => !names.includes(rel))
  return { fresh: false, stale, extra, missing }
}

function write(files, outDir) {
  const current = readOutput(outDir)
  if (current !== null) {
    // Replace, don't merge: a stale file left behind would ship a doc the
    // source no longer has.
    const names = files.map((f) => f.rel)
    const extra = [...current.keys()].filter((rel) => !names.includes(rel))
    for (const rel of extra) rmSync(join(outDir, rel))
  }
  for (const { rel, text } of files) {
    const path = join(outDir, rel)
    mkdirSync(dirname(path), { recursive: true })
    writeFileSync(path, text, 'utf8')
  }
}

function main() {
  const options = parseArgs(process.argv.slice(2))
  const sourceDir = join(ROOT, SOURCE_REL)
  const outDir = options.out ?? join(ROOT, DEFAULT_OUT_REL)

  const files = readSource(sourceDir)
  console.log(`source  ${shown(sourceDir)}  (${files.length} files)`)
  console.log(`out     ${options.out === null ? shown(outDir) : outDir}`)

  if (options.check) {
    const { fresh, stale, extra, missing } = diff(files, outDir)
    if (fresh) {
      console.error(`FAIL  ${shown(outDir)} does not exist; run the build first`)
      process.exit(1)
    }
    for (const rel of missing) console.error(`FAIL  missing: ${rel}`)
    for (const rel of stale) console.error(`FAIL  stale:   ${rel}`)
    for (const rel of extra) console.error(`FAIL  extra:   ${rel}`)
    if (stale.length + extra.length + missing.length > 0) {
      console.error(`\n${stale.length + extra.length + missing.length} file(s) differ; re-run the build`)
      process.exit(1)
    }
    console.log(`\nin sync (${files.length} files, line endings normalised)`)
    return
  }

  const { fresh, stale, extra, missing } = diff(files, outDir)
  const changed = fresh
    ? files.map((f) => `new       ${f.rel}`)
    : [
        ...missing.map((rel) => `new       ${rel}`),
        ...stale.map((rel) => `stale     ${rel}`),
        ...extra.map((rel) => `obsolete  ${rel}`),
      ]

  if (options.dryRun) {
    if (changed.length === 0) console.log('\nnothing to do')
    else for (const line of changed) console.log(line)
    return
  }

  write(files, outDir)
  if (changed.length === 0) console.log('\nnothing to do')
  else for (const line of changed) console.log(line)
}

main()
