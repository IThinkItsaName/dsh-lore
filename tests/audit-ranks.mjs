// Catalog-rank relations for the plugin's two providers.
//
// Why this exists: rank decides which same-name skill wins, and losing that
// comparison is SILENT — the skill simply does not appear, with no error anywhere.
// That is how a pair of file copies in `.dsh/skills` shadowed this plugin for
// several rounds while every check still reported PASS.
//
// Scope, stated honestly: this check can only pin the relations whose reference
// values are knowable from here — the plugin's own rank, the filesystem provider's
// documented ranks, and the registry's `RUNTIME_RANK`. It does NOT verify cross-
// layer precedence, which is a property of how a composition mounts providers and
// cannot be observed from a package. See the comment on PROVIDER_RANK.
//
//   node tests/audit-ranks.mjs
import { readFileSync } from 'node:fs'
import { PKG } from './_pkg.mjs'

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}

const src = readFileSync(`${PKG}/lib/index.js`, 'utf8')

const rank = Number(/const PROVIDER_RANK = (\d+)/.exec(src)?.[1])
ok(Number.isFinite(rank), 'read PROVIDER_RANK from the entry', String(rank))

/* The registry's own runtime rank — the value a same-layer register() would use. */
let runtimeRank
let registryPath = ''
for (const candidate of [
  process.env.DSH_SKILL_SRC ?? '',
  `${PKG}/../../logs/dsh-src/dsh/node_modules/@deepseek-ai/dsh-skill/lib/index.js`,
  `${PKG}/../../logs/dsh-src/full/dsh-skill/lib/index.js`,
].filter(Boolean)) {
  try {
    const text = readFileSync(candidate, 'utf8')
    const m = /const RUNTIME_RANK = (\d+)/.exec(text)
    if (m) { runtimeRank = Number(m[1]); registryPath = candidate; break }
  } catch { /* try the next */ }
}

if (runtimeRank === undefined) {
  ok(true, 'registry RUNTIME_RANK cross-check SKIPPED (set DSH_SKILL_SRC to enable it)')
} else {
  console.log(`      registry: ${registryPath}`)
  ok(rank > runtimeRank,
     `PROVIDER_RANK (${rank}) is ABOVE the registry's RUNTIME_RANK (${runtimeRank})`,
     'a same-layer register() wins a name collision; lower the rank to outrank it')
}

/*
 * The filesystem provider's root ranks, from its documented order. Only the ones
 * that share a layer with a bundle-supplied provider are meaningful here.
 */
const FS_RANKS = { projectDsh: 100, projectAgents: 200, customDirs: 300, dshHome: 400, agentsHome: 500 }
console.log(`      filesystem roots: ${JSON.stringify(FS_RANKS)}`)

ok(rank > FS_RANKS.projectDsh && rank > FS_RANKS.projectAgents,
   `PROVIDER_RANK (${rank}) does not try to outrank project-local roots`,
   'project-local roots win on layer precedence; competing on rank would be meaningless')
ok(rank < FS_RANKS.dshHome,
   `PROVIDER_RANK (${rank}) outranks the user-level ~/.dsh/skills root (${FS_RANKS.dshHome})`,
   "this bundle's own copy should win over a stale user-level copy")
ok(rank < FS_RANKS.agentsHome,
   `PROVIDER_RANK (${rank}) outranks the user-level ~/.agents/skills root (${FS_RANKS.agentsHome})`)
ok(rank > FS_RANKS.customDirs,
   `PROVIDER_RANK (${rank}) lets a project's customSkillDirs (${FS_RANKS.customDirs}) win`,
   'an explicitly configured project root should outrank a bundle')

/* A stable default is itself worth pinning: changing it changes shadowing. */
ok(rank === 350, 'PROVIDER_RANK is the reviewed default (350)', String(rank))

console.log(problems.length === 0 ? '\ncatalog rank relations OK' : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
