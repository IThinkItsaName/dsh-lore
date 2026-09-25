import { appendFileSync, readFileSync } from 'node:fs'
import { dirname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Diagnostic trace, off unless armed.
 *
 * A skill provider has no easy way to see its own failures: the registry
 * catches them and logs one line to the host logger, which an out-of-tree plugin
 * author cannot read. Arm this to record what the host actually asks for.
 *
 * Arm it one of two ways:
 *   - set `DSH_WORKLOG_TRACE` to a file path, or
 *   - write the target path into `<package>/lib/.trace`
 *
 * It logs `apply` (with whether `ctx.skills` was available), every `list()`
 * (with the registry's lookup scope and cwd, which is what identifies the
 * caller), and every `get()`.
 */
function trace(event, detail) {
  let target = process.env.DSH_WORKLOG_TRACE
  if (target === undefined) {
    const marker = join(dirname(fileURLToPath(import.meta.url)), '.trace')
    try {
      target = readFileSync(marker, 'utf8').trim()
    } catch {
      return
    }
  }
  if (target === '') return
  try {
    appendFileSync(target, `${new Date().toISOString()} ${event} ${detail ?? ''}\n`)
  } catch {
    /* a broken trace target must never break the plugin */
  }
}

/**
 * DSH plugin entry for the worklog skill bundle.
 *
 * This package ships the `project-work-log` Agent Skill as a directory bundle
 * under `skills/project-work-log/`. The plugin registers that bundle with the
 * skill registry (`ctx.skills`), so a DSH profile that installs this bundle
 * gets the skill in its session catalog without copying any file and without
 * configuring a skill search root.
 *
 * The Markdown stays the single source of truth: this module parses the
 * bundle's YAML frontmatter at load time and registers the skill from it.
 *
 * Design notes:
 * - `register` (not `registerProvider`) is deliberate. A provider would have to
 *   re-implement frontmatter parsing and catalog ranking; the registry's runtime
 *   path already validates names, descriptions, and invocation policy, and
 *   loads the body on demand.
 * - Frontmatter parsing is implemented here instead of importing a YAML library,
 *   because this bundle must stay dependency-free (no `pnpm add` step, no
 *   install-time network access). It accepts exactly the frontmatter shape the
 *   Agent Skills specification defines: flat `key: value` scalars.
 * - There is deliberately **no `Config` export and no imports outside `node:`**.
 *   A plugin installed into a profile resolves its imports from its own real
 *   path, and `@deepseek-ai/schemastery` exists only inside the application's
 *   `app.asar` — so a `Config` schema cannot be built by an out-of-tree plugin,
 *   and a static import of it makes the whole module fail to load. Configuration
 *   is therefore read defensively from the row's plain object with defaults
 *   applied here.
 *
 * @module dsh-worklog
 */

const HERE = dirname(fileURLToPath(import.meta.url))
/** Package root: this module lives in `<package>/lib/`, one level below it. */
const PACKAGE_ROOT = resolve(HERE, '..')

/** Default skill bundle, relative to the package root. */
const DEFAULT_SKILL_DIR = 'skills/project-work-log'
/** Instruction file name inside a skill bundle. */
const SKILL_FILE = 'SKILL.md'
/** Kebab-case skill name, mirrored from the registry's own validation. */
const SKILL_NAME_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
/** Frontmatter keys this bundle forwards to the registry. */
const KNOWN_KEYS = ['name', 'description', 'whenToUse', 'user-invocable', 'disable-model-invocation']
/** Row-config keys this plugin understands. */
const KNOWN_CONFIG_KEYS = [
  'skillDir', 'skillFile', 'modelInvocable', 'userInvocable', 'verbose',
  'guidelinesEnabled', 'guidelinesDir', 'guidelinesLanguage',
]
/**
 * Provider name registered on `ctx.skills` for the work-record skill.
 *
 * `runtime` is reserved by the registry for `register()` contributions, and two
 * providers may not share a name, so each skill gets its own.
 */
const PROVIDER_NAME = 'worklog-bundle'
/** Provider name for the reliability-guidelines skill. */
const GUIDELINES_PROVIDER_NAME = 'worklog-guidelines'
/** Catalog rank: a bundle-supplied skill, below project-local discovery. */
const PROVIDER_RANK = 350
/** Second skill shipped by this bundle. */
const DEFAULT_GUIDELINES_DIR = 'skills/reliability-guidelines'
/** English copy, kept in a subdirectory so the one-level filesystem scan misses it. */
const GUIDELINES_EN_FILE = join('en', SKILL_FILE)

export const name = 'dsh-worklog'

/**
 * Declared service dependencies. The registry is owned by `@deepseek-ai/dsh-skill`;
 * `@deepseek-ai/dsh-tool-skill` is the consumer that renders the catalog and the
 * `skill` tool, and it is what makes the registered skill reachable by a model.
 */
export const inject = ['skills']

/* -------------------------------------------------------------------------- */
/* error containment                                                          */
/* -------------------------------------------------------------------------- */

/** Render any thrown value without letting coercion escape. */
function errorMessage(error) {
  try {
    return String(error)
  } catch {
    return '[unrenderable thrown value]'
  }
}

/* -------------------------------------------------------------------------- */
/* frontmatter                                                                */
/* -------------------------------------------------------------------------- */

/**
 * Strip one layer of matching quotes and resolve the escape forms the
 * specification's YAML subset allows. Returns the raw text when it is not
 * quoted, so unquoted Chinese prose survives verbatim.
 */
function unquote(value) {
  const first = value.slice(0, 1)
  const last = value.slice(-1)
  const quoted = value.length >= 2 && (first === '"' || first === "'") && last === first
  if (!quoted) return value
  const body = value.slice(1, -1)
  if (first === "'") return body.replaceAll("''", "'")
  return body.replace(/\\(["\\/nrt])/g, (_, ch) => {
    switch (ch) {
      case 'n': return '\n'
      case 'r': return '\r'
      case 't': return '\t'
      default: return ch
    }
  })
}

/**
 * Read a flat `key: value` frontmatter block.
 *
 * Accepts an optional leading BOM (editors on Windows add one), requires the
 * opening `---` on the first line, and requires a closing `---` line. A block
 * scalar (`|` / `>`) or a nested mapping is rejected by `parseSkillFrontmatter`
 * rather than silently mis-parsed into a name or description.
 *
 * @returns the raw key → value map, or `undefined` when no block is present.
 */
export function readFrontmatter(text) {
  const body = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text
  const lines = body.split(/\r?\n/)
  if (lines[0]?.trim() !== '---') return undefined
  let end = -1
  for (let i = 1; i < lines.length; i += 1) {
    const line = lines[i].trim()
    if (line === '---' || line === '...') { end = i; break }
  }
  if (end === -1) return undefined

  const data = {}
  let i = 1
  while (i < end) {
    const line = lines[i]
    if (line.trim() === '' || line.trimStart().startsWith('#')) { i += 1; continue }
    // Only top-level keys exist in this subset; indentation means a nested block.
    if (/^[ \t]/.test(line)) { i += 1; continue }
    const match = /^([A-Za-z0-9_.-]+)\s*:\s*(.*)$/.exec(line)
    if (match === null) { i += 1; continue }
    const key = match[1]
    let value = match[2].trim()
    if (value === '|' || value === '>' || value === '|-' || value === '>-' || value === '|+' || value === '>+') {
      // Block scalar: consume the indented body and join it.
      const joiner = value.startsWith('>') ? ' ' : '\n'
      const chunk = []
      i += 1
      while (i < end && (lines[i].trim() === '' || /^[ \t]/.test(lines[i]))) {
        chunk.push(lines[i].trim())
        i += 1
      }
      data[key] = chunk.join(joiner).trim()
      continue
    }
    data[key] = unquote(value)
    i += 1
  }
  return data
}

/** Parse a lenient boolean; returns `undefined` for an unrecognized spelling. */
function parseBoolean(value) {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim().toLowerCase()
  if (['true', 'yes', 'on', '1'].includes(normalized)) return true
  if (['false', 'no', 'off', '0'].includes(normalized)) return false
  return undefined
}

/**
 * Parse `SKILL.md` into the fields the registry validates.
 *
 * @param text - the raw instruction file.
 * @param subject - label used in error messages (usually the file path).
 * @returns name, description, optional whenToUse, and the resolved invocation policy.
 * @throws Error when frontmatter is missing or a required field is invalid.
 */
export function parseSkillFrontmatter(text, subject = SKILL_FILE) {
  const data = readFrontmatter(text)
  if (data === undefined) throw new Error(`${subject}: missing YAML frontmatter block (--- ... ---)`)

  const skillName = (data.name ?? '').trim()
  if (!SKILL_NAME_RE.test(skillName)) {
    throw new Error(`${subject}: frontmatter "name" must be kebab-case, received ${JSON.stringify(data.name ?? '')}`)
  }
  const description = (data.description ?? '').trim()
  if (description === '') throw new Error(`${subject}: frontmatter "description" is required`)

  const whenToUse = (data.whenToUse ?? '').trim()
  const modelFlag = parseBoolean(data['disable-model-invocation'])
  const userFlag = parseBoolean(data['user-invocable'])
  for (const [key, raw, parsed] of [
    ['disable-model-invocation', data['disable-model-invocation'], modelFlag],
    ['user-invocable', data['user-invocable'], userFlag],
  ]) {
    if (raw !== undefined && parsed === undefined) {
      throw new Error(`${subject}: frontmatter "${key}" must be a boolean, received ${JSON.stringify(raw)}`)
    }
  }

  const unknown = Object.keys(data).filter((key) => !KNOWN_KEYS.includes(key))
  return {
    name: skillName,
    description,
    ...whenToUse === '' ? {} : { whenToUse },
    invocation: {
      // `disable-model-invocation: true` removes the model surface; omitted permits it.
      modelInvocable: modelFlag === true ? false : true,
      userInvocable: userFlag === false ? false : true,
    },
    unknown,
  }
}

/* -------------------------------------------------------------------------- */
/* plugin                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Resolve the bundle directory against this **package root**.
 *
 * `HERE` is the directory of this module (`<package>/lib`), so a relative
 * `skillDir` must climb out of `lib/` before resolving — resolving against
 * `HERE` would look for `<package>/lib/skills/...`.
 */
function resolveSkillDir(ctx, dir) {
  if (isAbsolute(dir)) return dir
  const base = process.env.DSH_WORKLOG_BASE ?? PACKAGE_ROOT
  return resolve(base, dir)
}

/**
 * Return the instruction body: everything after the closing frontmatter line.
 *
 * The registry wraps whatever it receives in `<skill_instructions>` and renders
 * it for the model, so the frontmatter block (already consumed into the catalog
 * entry) must not be repeated in the body.
 */
export function stripFrontmatter(text) {
  const body = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text
  const lines = body.split(/\r?\n/)
  if (lines[0]?.trim() !== '---') return body
  for (let i = 1; i < lines.length; i += 1) {
    const line = lines[i].trim()
    if (line === '---' || line === '...') return lines.slice(i + 1).join('\n').replace(/^\n+/, '')
  }
  return body
}

/** Describe the lookup options the registry passes, to identify the caller. */
function describeLookup(options) {
  if (options === undefined || options === null) return ' opts=<none>'
  const scope = options.scope
  const scopeName = typeof scope === 'object' && scope !== null
    ? (scope.constructor?.name ?? 'object')
    : String(scope)
  const cwd = typeof options.cwd === 'string' ? options.cwd : '<none>'
  const aborted = options.signal?.aborted === true
  return ` scope=${scopeName} cwd=${cwd} aborted=${aborted}`
}

/**
 * Build one provider serving a single skill bundle.
 *
 * `providerName` must be unique per provider (`runtime` is reserved), and the
 * candidate and definition it produces must both carry it — the registry
 * validates `candidate.provider === providerName`.
 *
 * A provider (rather than `ctx.skills.register`) is what keeps a skill live.
 * `register` captures `content` once at mount and the registry hands that exact
 * object back on every load, so an edit to `SKILL.md` would need a host restart.
 * A provider re-reads the file on every `list()`/`get()`, which matches how the
 * shipped filesystem provider behaves: the catalog and the body have separate
 * lifecycles, and only the catalog is cached.
 */
function createProvider({ providerName, label, dir, file, options, ctx }) {
  /** Last catalog that parsed successfully, so a transient read failure is not a deletion. */
  let lastGood

  /** Read and parse the instruction file, or throw with a labelled message. */
  function readSkill() {
    const raw = readFileSync(file, 'utf8')
    return { raw, parsed: parseSkillFrontmatter(raw, file) }
  }

  /** Project a parsed instruction file onto the candidate/definition fields. */
  function project(parsed) {
    return {
      name: parsed.name,
      description: parsed.description,
      ...(parsed.whenToUse === undefined ? {} : { whenToUse: parsed.whenToUse }),
      invocation: {
        modelInvocable: options.modelInvocable && parsed.invocation.modelInvocable,
        userInvocable: options.userInvocable && parsed.invocation.userInvocable,
      },
      provider: providerName,
      source: label,
      // Resolve relative paths in the instructions against the real bundle, so
      // `references/*.md` and `scripts/journal.py` are readable without a copy.
      resourceBase: { kind: 'directory', path: dir },
      // Advertised for discovery consumers that offer a file preview.
      path: file,
    }
  }

  return {
    name: providerName,
    /**
     * Report the catalog. Candidates carry a `rank`; the registry reserves
     * `runtime` as a provider name, so this uses its own.
     *
     * `complete: false` after a failed read keeps the registry from caching a
     * misleading empty catalog, and the last good candidate is still offered so
     * the skill does not blink out of a session on a transient error.
     */
    list(options) {
      try {
        const { parsed } = readSkill()
        const candidate = { ...project(parsed), rank: PROVIDER_RANK, locator: parsed.name }
        lastGood = candidate
        if (parsed.unknown.length > 0) {
          ctx.logger.warn(`worklog: ignoring unsupported frontmatter keys: ${parsed.unknown.join(', ')}`)
        }
        trace('list', `ok complete=true candidates=1 name=${candidate.name}${describeLookup(options)}`)
        return { candidates: [candidate], complete: true }
      } catch (error) {
        ctx.logger.error(`worklog: ${errorMessage(error)}`)
        trace('list', `error=${errorMessage(error)}${describeLookup(options)}`)
        return lastGood === undefined
          ? { candidates: [], complete: false }
          : { candidates: [lastGood], complete: false }
      }
    },
    /** Load the body: re-read the file so edits show up without a restart. */
    get(candidate, options) {
      try {
        const { raw, parsed } = readSkill()
        if (parsed.name !== candidate.name) {
          trace('get', `stale name=${parsed.name} asked=${candidate.name}${describeLookup(options)}`)
          return undefined
        }
        trace('get', `ok name=${parsed.name} bytes=${raw.length}${describeLookup(options)}`)
        return { ...project(parsed), content: stripFrontmatter(raw) }
      } catch (error) {
        trace('get', `error=${errorMessage(error)}${describeLookup(options)}`)
        throw error
      }
    },
  }
}

/** Coerce a row-config value to a boolean, falling back when it is not one. */
function boolOr(value, fallback) {
  return typeof value === 'boolean' ? value : fallback
}

/** Coerce a row-config value to a non-empty string, falling back when it is not one. */
function stringOr(value, fallback) {
  return typeof value === 'string' && value.trim() !== '' ? value : fallback
}

/**
 * Register this bundle's skills with the registry.
 *
 * Two skills are served, by two providers:
 *   - `project-work-log` — the work-record system itself.
 *   - `reliability-guidelines` — the eight working principles, shipped with the
 *     plugin so they apply in the projects that install it.
 *
 * No `Config` schema is exported (an out-of-tree plugin cannot build one — the
 * Schemastery package lives inside the application's asar), so the row's `config`
 * reaches this function unvalidated: every field is coerced defensively and
 * unknown keys are reported instead of silently ignored.
 *
 * Providers are used rather than `ctx.skills.register()` because a provider
 * re-reads its file on every `list()`/`get()`, so editing a `SKILL.md` shows up
 * on the next load; `register()` would snapshot the body at mount.
 */
export function apply(ctx, config = {}) {
  trace('apply', `enter hasSkills=${typeof ctx?.skills?.registerProvider === 'function'}`)
  const raw = config !== null && typeof config === 'object' && !Array.isArray(config) ? config : {}
  const options = {
    skillDir: stringOr(raw.skillDir, DEFAULT_SKILL_DIR),
    skillFile: stringOr(raw.skillFile, SKILL_FILE),
    modelInvocable: boolOr(raw.modelInvocable, true),
    userInvocable: boolOr(raw.userInvocable, true),
    verbose: boolOr(raw.verbose, false),
    guidelinesEnabled: boolOr(raw.guidelinesEnabled, true),
    guidelinesDir: stringOr(raw.guidelinesDir, DEFAULT_GUIDELINES_DIR),
    // Only 'en' is meaningful; anything else keeps the Chinese default so a typo
    // cannot silently produce a missing skill.
    guidelinesLanguage: raw.guidelinesLanguage === 'en' ? 'en' : 'zh',
  }

  const unknown = Object.keys(raw).filter((key) => !KNOWN_CONFIG_KEYS.includes(key))
  if (unknown.length > 0) {
    ctx.logger.warn(`worklog: ignoring unsupported config keys: ${unknown.join(', ')}`)
  }

  /**
   * Mount one bundle. Fails loudly when its instruction file is missing: a
   * provider that only ever returned an empty catalog would look identical to
   * "this skill was never installed".
   */
  function mount({ providerName, label, dir, file }) {
    let probe
    try {
      probe = parseSkillFrontmatter(readFileSync(file, 'utf8'), file)
    } catch (error) {
      ctx.logger.error(`worklog: ${errorMessage(error)}`)
      trace('apply', `probe-error=${errorMessage(error)} file=${file}`)
      return
    }
    if (probe.unknown.length > 0) {
      ctx.logger.warn(`worklog: ignoring unsupported frontmatter keys: ${probe.unknown.join(', ')}`)
    }
    ctx.skills.registerProvider((control) =>
      createProvider({ providerName, label, dir, file, options, ctx }))
    trace('apply', `registered provider=${providerName} skill=${probe.name} file=${file}`)
    if (options.verbose) {
      ctx.logger.info(`worklog: serving skill "${probe.name}" from ${file}`)
    }
  }

  const dir = resolveSkillDir(ctx, options.skillDir)
  mount({
    providerName: PROVIDER_NAME,
    label: 'worklog bundle',
    dir,
    file: join(dir, options.skillFile),
  })

  // The working principles, when enabled. Language picks which file is served;
  // the alternate language stays on disk under `en/`, where the filesystem
  // provider's one-level scan cannot find it and list it twice.
  if (options.guidelinesEnabled) {
    const guidelinesDir = resolveSkillDir(ctx, options.guidelinesDir)
    const guidelinesFile = join(
      guidelinesDir,
      options.guidelinesLanguage === 'en' ? GUIDELINES_EN_FILE : options.skillFile,
    )
    mount({
      providerName: GUIDELINES_PROVIDER_NAME,
      label: 'worklog guidelines',
      dir: guidelinesDir,
      file: guidelinesFile,
    })
  }
}
