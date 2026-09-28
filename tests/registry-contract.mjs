// Mirror the skill registry's own validation against every provider this plugin
// registers, so a host restart is not a guess.
//
// Source of truth (read out of the installed @deepseek-ai/dsh-skill lib/index.js):
//   normalizeProviderObservation(output, providerName)
//   validateCandidate(candidate, providerName)
//   validateDefinition(definition)        <- applied to whatever get() returns
//
//   node tests/registry-contract.mjs
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { PKG, extraBundledSkills } from './_pkg.mjs'

const SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

const mod = await import(pathToFileURL(`${PKG}/lib/index.js`).href)

const providers = []
const logs = []
const ctx = {
  logger: {
    info: (m) => logs.push(['info', String(m)]),
    warn: (m) => logs.push(['warn', String(m)]),
    error: (m) => logs.push(['error', String(m)]),
  },
  skills: { registerProvider: (create) => { providers.push(create); return () => {} } },
}

mod.apply(ctx, {})

const problems = []
const ok = (condition, label, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${label}${condition || !detail ? '' : ` -- ${detail}`}`)
  if (!condition) problems.push(label)
}

ok(providers.length === 2 + extraBundledSkills().length,
   'apply() registers one provider per skill bundle on disk',
   String(providers.length))
ok(logs.filter(([level]) => level === 'error').length === 0, 'apply() logged no error',
   JSON.stringify(logs))

/** Apply the registry's own rules to one provider's output. */
async function checkProvider(create, expectedSkill) {
  const provider = create({ signal: new AbortController().signal, invalidate: () => {} })
  const at = (label) => `${expectedSkill}: ${label}`

  ok(provider.name !== 'runtime', at('provider name is not the reserved "runtime"'), provider.name)

  /* ---- the registry's waitWithAbort() calls `.then` on whatever these return,
     whenever a signal is present. A synchronous return crashes the run with
     `promise.then is not a function`. ---- */
  const isPromise = (v) => v !== null && typeof v === 'object' && typeof v.then === 'function'
  const listCall = provider.list({ cwd: 'X', scope: {} })
  ok(isPromise(listCall), at('list() returns a promise (waitWithAbort calls .then)'),
     `got ${typeof listCall}`)

  /* ---- normalizeProviderObservation ---- */
  const observation = await listCall
  ok(observation !== null && typeof observation === 'object', at('list() returns an object'))
  ok(Array.isArray(observation.candidates), at('observation carries a candidates array'))
  ok(typeof observation.complete === 'boolean', at('observation carries a boolean complete'))
  ok(observation.complete === true, at('observation is complete'))

  /* ---- validateCandidate(candidate, provider.name) ---- */
  const cand = observation.candidates[0]
  ok(typeof cand.name === 'string' && SKILL_NAME.test(cand.name), at('candidate name is kebab-case'), cand.name)
  ok(cand.name === expectedSkill, at('candidate name is the expected skill'), cand.name)
  ok(typeof cand.description === 'string' && cand.description.length > 0,
     at('candidate description is a non-empty string'))
  ok(cand.whenToUse === undefined || typeof cand.whenToUse === 'string',
     at('candidate whenToUse is a string or absent'))
  ok(typeof cand.source === 'string', at('candidate source is a string'), typeof cand.source)
  ok(typeof cand.rank === 'number' && Number.isFinite(cand.rank),
     at('candidate rank is a finite number'), String(cand.rank))
  ok(typeof cand.provider === 'string', at('candidate provider is a string'), typeof cand.provider)
  ok(cand.provider === provider.name,
     at('candidate.provider equals the provider name (a mismatch is fatal)'),
     `${cand.provider} vs ${provider.name}`)
  ok(cand.path === undefined || typeof cand.path === 'string', at('candidate path is a string or absent'))
  ok(typeof cand.invocation?.modelInvocable === 'boolean' && typeof cand.invocation?.userInvocable === 'boolean',
     at('both invocation flags are booleans'))

  /* ---- validateDefinition(definition) on what get() returns ---- */
  const getCall = provider.get(cand, { cwd: 'X', scope: {} })
  ok(isPromise(getCall), at('get() returns a promise (waitWithAbort calls .then)'),
     `got ${typeof getCall}`)
  const def = await getCall
  ok(typeof def.name === 'string' && SKILL_NAME.test(def.name), at('definition name is kebab-case'))
  ok(typeof def.description === 'string' && def.description.length > 0,
     at('definition description is a non-empty string'))
  ok(typeof def.source === 'string', at('definition source is a string'))
  ok(typeof def.provider === 'string', at('definition provider is a string'), typeof def.provider)
  ok(typeof def.content === 'string',
     at('definition content IS A STRING  <-- the field that failed on the first install'),
     `content is ${typeof def.content}`)
  ok(def.content.length > 100, at('definition content is non-trivial'), `${def.content.length} chars`)
  ok(def.path === undefined || typeof def.path === 'string', at('definition path is a string or absent'))
  ok(def.whenToUse === undefined || typeof def.whenToUse === 'string',
     at('definition whenToUse is a string or absent'))

  /* ---- the registry rejects a stale selection whose name changed ---- */
  ok(def.name === cand.name, at('get() returns the name it was asked for (no stale selection)'))

  /* ---- the rendered body must be the real skill, resolvable via resourceBase ---- */
  ok(!def.content.startsWith('---'), at('rendered body does not begin with frontmatter'))
  ok(def.content.trimStart().startsWith('# '), at('rendered body starts at the H1'))
  ok(def.resourceBase?.kind === 'directory', at('resourceBase is a directory'))
  ok(typeof def.resourceBase.path === 'string', at('resourceBase carries a path'))
  ok(readFileSync(def.path, 'utf8').length > 0, at('the instruction file is readable at the advertised path'))
  return def
}

const worklogDef = await checkProvider(providers[0], 'project-work-log')
ok(worklogDef.content.includes('## 铁律'), 'worklog: body contains the skill sections')
ok(worklogDef.content.includes('scripts/journal.py'),
   'worklog: body still points at scripts/journal.py, which resourceBase resolves')

const guidDef = await checkProvider(providers[1], 'reliability-guidelines')
ok(guidDef.content.includes('八条准则'), 'guidelines: zh body contains the eight principles')
ok(guidDef.content.includes('默认强约束'), 'guidelines: body frames itself as a strong default')

console.log(problems.length === 0
  ? '\nevery provider output satisfies the rules the registry applies'
  : `\n${problems.length} FAILED`)
process.exit(problems.length === 0 ? 0 : 1)
