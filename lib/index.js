import { appendFileSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
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
 * This package ships two Agent Skills as directory bundles —
 * `skills/project-work-log/` and `skills/reliability-guidelines/`. The plugin
 * registers both with the skill registry (`ctx.skills`), so a DSH profile that
 * installs this bundle gets them in its session catalog without copying any file
 * and without configuring a skill search root.
 *
 * The Markdown stays the single source of truth: this module parses each
 * bundle's YAML frontmatter at mount time, then serves the body by re-reading the
 * file on every load.
 *
 * Design notes:
 * - A **provider** is registered, not a single skill. `ctx.skills.register()`
 *   captures `content` once at mount and the registry hands that exact object
 *   back on every load, so editing a `SKILL.md` would need a host restart. A
 *   provider re-reads the file on each `list()`/`get()`, which is what the
 *   shipped filesystem provider does: the catalog and the body have separate
 *   lifecycles, and only the catalog is cached.
 * - Frontmatter parsing is implemented here instead of importing a YAML library,
 *   because this bundle must stay dependency-free (no `pnpm add` step, no
 *   install-time network access). It accepts the subset the Agent Skills
 *   specification defines: flat `key: value` scalars, plus quoted forms and
 *   block scalars.
 * - There is deliberately **no `Config` export and no imports outside `node:`**.
 *   A plugin installed into a profile resolves its imports from its own real
 *   path, and `@deepseek-ai/schemastery` exists only inside the application's
 *   `app.asar` — so a `Config` schema cannot be built by an out-of-tree plugin,
 *   and a static import of it makes the whole module fail to load. Configuration
 *   is therefore read defensively from the row's plain object with defaults
 *   applied here.
 *
 * The client half (`lib/client.js`) is a settings page. It cannot touch the
 * filesystem, so this module also serves its own settings file over one HTTP
 * route (`GET`/`POST /plugins/dsh-worklog/settings.json`) — the same shape
 * `dsh-status-rotator` uses rather than the DSH `Config`/settings-scope
 * mechanism, which an out-of-tree plugin cannot build.
 *
 * Effective configuration is the merge of three layers, highest first:
 *
 *   1. the settings file (what the settings page writes) — the user's explicit
 *      choice, so it beats the deployment's own values;
 *   2. the row config from the bundle patch (`cordis.patch.yml`);
 *   3. the built-in defaults below.
 *
 * Layer 1 has to beat layer 2 or the page would be inert: this bundle's patch
 * row declares `guidelinesEnabled`/`guidelinesLanguage`/`skillDir`/
 * `guidelinesDir` outright, and those values are always present.
 *
 * The page also collects three **project-side** defaults (`container`,
 * `lessons`, `mode`). Those are stored and reported, never resolved: they seed a
 * new project's own `<container>/.config.json`, which `journal.py` reads. They are
 * deliberately absent from `effectiveSettings()` — see `PROJECT_DEFAULT_KEYS` and
 * `projectDefaults()`.
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
 * Settings-page keys this plugin stores but does **not** act on.
 *
 * These are the project-side defaults the settings page collects for the
 * project initializer (`<container>/.config.json`). Keeping them in a separate
 * list is the point: this module reads its own configuration and nothing else,
 * and the moment `container`/`lessons`/`mode` join `KNOWN_CONFIG_KEYS` it starts
 * claiming to honour a value that only `journal.py` and the project file decide.
 * The one rule the whole two-surface design rests on is that the two surfaces do
 * not manage the same thing — and `tests/audit-doc-consistency.mjs` derives the
 * documented config surface from `KNOWN_CONFIG_KEYS`, so it would otherwise
 * demand documentation for keys this module does not read.
 *
 * The settings file keeps them because the page must be able to save them; the
 * plugin just refuses to pretend they change anything on the plugin side. The
 * settings route reports them through `projectDefaults()`, which carries the
 * `appliedByPlugin: false` marker the page labels them with, so "stored" and "in
 * effect" cannot be confused on either side of the route.
 */
const PROJECT_DEFAULT_KEYS = ['container', 'lessons', 'mode']
/**
 * Provider name registered on `ctx.skills` for the work-record skill.
 *
 * `runtime` is reserved by the registry for `register()` contributions, and two
 * providers may not share a name, so each skill gets its own.
 */
const PROVIDER_NAME = 'worklog-bundle'
/** Provider name for the reliability-guidelines skill. */
const GUIDELINES_PROVIDER_NAME = 'worklog-guidelines'
/**
 * Catalog rank for both providers.
 *
 * Confidence in this number is low, so state what it actually does rather than
 * what it was hoped to do. The registry sorts candidates by rank **ascending**
 * (lower wins), but rank only decides same-name duplicates **within one layer**:
 * across layers, layer precedence governs — project entries beat runtime entries,
 * which beat user entries — and the rank number plays no part.
 *
 * So the earlier claim that 350 puts the bundle "below project-local discovery"
 * was wrong: project-local roots win on layer precedence regardless of this value.
 * What 350 really sits between is the roots that share the plugin's layer, using
 * the filesystem provider's own ranks: project-local roots are 100/200, the
 * `customSkillDirs` root is 300, ours is 350, and the user-level roots are
 * 400/500. A user-level copy is therefore shadowed by this bundle's copy.
 *
 * The value that matters most is the one it is *above*: the registry's own
 * `RUNTIME_RANK` is 250, so a same-layer `ctx.skills.register()` wins over this
 * provider on a name collision. `tests/audit-ranks.mjs` pins these relations
 * against the registry's constants, because a silent change here loses the skill
 * with no error — which is exactly how the file-copy shadowing went unnoticed for
 * several rounds.
 */
const PROVIDER_RANK = 350
/** Second skill shipped by this bundle. */
const DEFAULT_GUIDELINES_DIR = 'skills/reliability-guidelines'
/** English copy, kept in a subdirectory so the one-level filesystem scan misses it. */
const GUIDELINES_EN_FILE = join('en', SKILL_FILE)
/** Directory under the DSH home that holds this plugin's settings file. */
const SETTINGS_DIR_NAME = 'worklog'
/** Settings file name, inside {@link SETTINGS_DIR_NAME}. */
const SETTINGS_FILE_NAME = 'settings.json'
/** HTTP route the client half reads and writes that file through. */
const SETTINGS_ROUTE_PATH = '/plugins/dsh-worklog/settings.json'
/**
 * Largest request body the settings route accepts.
 *
 * The document is a handful of scalars, so the cap is about refusing an
 * unbounded read, not about a real payload: `dsh-status-rotator` allows 5 MiB
 * for a 70 KB phrase bank, and 256 KiB is already a thousand times this one.
 */
const SETTINGS_BODY_LIMIT = 256 * 1024
/** Values `mode` (new-project default granularity) accepts. */
const MODES = ['full', 'session', 'digest', 'milestone']
/** Default container directory name for a new project (`container`). */
const DEFAULT_CONTAINER = 'work_log'
/** Default lessons directory name for a new project (`lessons`). */
const DEFAULT_LESSONS = 'lessons'

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

/** Render a filesystem path with forward slashes, for readable log messages. */
function toSlashes(path) {
  return String(path ?? '').replaceAll('\\', '/')
}

/** Render any thrown value without letting coercion escape. */
function errorMessage(error) {
  try {
    return String(error)
  } catch {
    return '[unrenderable thrown value]'
  }
}

/**
 * The reason inside an error message, with the leading `Error:` kind and the
 * caller-supplied subject path stripped.
 *
 * `parseSkillFrontmatter` prefixes its message with the subject it was given,
 * which is the same file path the caller already names — without this the path is
 * printed twice in one line.
 */
function reasonOf(error, subject) {
  return errorMessage(error)
    .replace(/^\w*Error:\s*/, '')
    .replace(String(subject ?? ''), '')
    .replace(/^[:\s]+/, '')
    .trim()
}

/**
 * Log through the host context, tolerating its absence.
 *
 * `ctx.logger` is not part of the contract this plugin can rely on: only `skills`
 * is declared in `inject`, and a logger that is missing, partial, or replaced by a
 * non-function is not impossible. Calling it directly would throw from `apply()`
 * or from a provider's `list()` — and the first failure mode is the bad one, a
 * crash during mount that takes the whole row down over a log line.
 *
 * The plugin already probes before touching `ctx.skills.registerProvider`, so
 * probing before logging is the same rule applied consistently rather than a new
 * defence.
 *
 * Falls back to `console.error` rather than dropping the message: a diagnostic
 * nobody can see is the failure this plugin's own trace exists to work around.
 */
function log(ctx, level, message) {
  const sink = ctx?.logger?.[level]
  if (typeof sink === 'function') {
    try {
      sink.call(ctx.logger, message)
      return
    } catch {
      /* fall through to the console */
    }
  }
  try {
    console.error(message)
  } catch {
    /* nowhere left to report to */
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
 * opening `---` on the first line, and requires a closing `---` line.
 *
 * Handles the three value forms the specification allows for a flat block:
 * a plain scalar, a quoted scalar (single or double, with the escapes `unquote`
 * resolves), and a block scalar (`|` literal or `>` folded, including the `-`/`+`
 * chomping variants), whose indented body is joined with newlines or spaces
 * respectively.
 *
 * A nested mapping is not rejected: its indented lines are skipped and the key
 * itself surfaces in `parseSkillFrontmatter`'s `unknown` list, so an unexpected
 * block is reported to the operator rather than silently parsed into a field.
 *
 * @param text - the raw instruction file.
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
 * Resolve a bundle directory against this **package root**.
 *
 * `HERE` is the directory of this module (`<package>/lib`), so a relative
 * `skillDir` must climb out of `lib/` before resolving — resolving against
 * `HERE` would look for `<package>/lib/skills/...`.
 *
 * An absolute `skillDir` is returned as-is, which is the documented way to point
 * the plugin at a bundle outside this package. There is deliberately no
 * environment-variable override for the base: an undocumented second way to
 * relocate the bundle would only be exercised by whoever added it, and the
 * absolute-path form is already covered by the config table in README.md.
 */
function resolveSkillDir(dir) {
  if (isAbsolute(dir)) return dir
  return resolve(PACKAGE_ROOT, dir)
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
     * MUST be `async`. The registry passes this call through
     * `waitWithAbort(value, signal)`, which does `value.then(...)` whenever a
     * signal is present — so a synchronous return crashes the run with
     * `promise.then is not a function`. Returning a promise is also what the
     * shipped filesystem provider does.
     *
     * `complete: false` after a failed read keeps the registry from caching a
     * misleading empty catalog, and the last good candidate is still offered so
     * the skill does not blink out of a session on a transient error.
     */
    async list(options) {
      try {
        const { parsed } = readSkill()
        const candidate = { ...project(parsed), rank: PROVIDER_RANK, locator: parsed.name }
        lastGood = candidate
        if (parsed.unknown.length > 0) {
          log(ctx, 'warn', `worklog: ignoring unsupported frontmatter keys: ${parsed.unknown.join(', ')}`)
        }
        trace('list', `ok complete=true candidates=1 name=${candidate.name}${describeLookup(options)}`)
        return { candidates: [candidate], complete: true }
      } catch (error) {
        log(ctx, 'error', `worklog: ${errorMessage(error)}`)
        trace('list', `error=${errorMessage(error)}${describeLookup(options)}`)
        return lastGood === undefined
          ? { candidates: [], complete: false }
          : { candidates: [lastGood], complete: false }
      }
    },
    /**
     * Load the body: re-read the file so edits show up without a restart.
     *
     * Also `async`, for the same `waitWithAbort` reason as `list()`.
     *
     * A name that moved under the selection returns a definition whose name
     * differs from the candidate. The registry detects that, invalidates the
     * cached catalogs and reports no skill — which is why this must NOT return
     * `undefined` to mean the same thing: `undefined` is not a promise, and
     * `waitWithAbort` would crash on it.
     */
    async get(candidate, options) {
      try {
        const { raw, parsed } = readSkill()
        if (parsed.name !== candidate.name) {
          trace('get', `stale name=${parsed.name} asked=${candidate.name}${describeLookup(options)}`)
          // Same fields as the normal path, but the registry's name check
          // rejects it and invalidates the stale catalog.
          return { ...project(parsed), content: stripFrontmatter(raw) }
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

/* -------------------------------------------------------------------------- */
/* settings file                                                              */
/* -------------------------------------------------------------------------- */

/**
 * The DSH home directory: `$DSH_HOME` when set, else `~/.dsh`.
 *
 * Same convention as DSH itself and as `dsh-status-rotator`, so everything a
 * DSH user configures lives under one directory. The override is what makes
 * this testable and what lets a portable install relocate the whole home.
 */
export function dshHomeDirectory() {
  const fromEnv = process.env.DSH_HOME
  if (typeof fromEnv === 'string' && fromEnv.trim() !== '') return fromEnv.trim()
  return join(homedir(), '.dsh')
}

/**
 * Absolute path of this plugin's settings file.
 *
 * Under `<DSH home>/worklog/settings.json`, NOT next to the package. The
 * package directory is the wrong home for it for two concrete reasons:
 *
 *   - a profile installs this package with a `link:` into a checkout that is
 *     usually a git working tree, so writing there dirties the tree and (worse)
 *     invites committing a user's settings;
 *   - a package reinstall or upgrade replaces that directory, which is exactly
 *     when losing the setting is most annoying.
 *
 * The home directory survives both. `DSH_WORKLOG_SETTINGS` overrides the whole
 * path, for a portable install and for the tests.
 */
export function settingsFilePath() {
  const override = process.env.DSH_WORKLOG_SETTINGS
  if (typeof override === 'string' && override.trim() !== '') return override.trim()
  return join(dshHomeDirectory(), SETTINGS_DIR_NAME, SETTINGS_FILE_NAME)
}

/** Whether a value is a plain JSON object (not null, not an array). */
function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/**
 * Read the settings file.
 *
 * Never throws: a missing file is the normal first-run state and a corrupt one
 * must not stop the plugin from mounting its skills, which is its actual job.
 * The caller is told which happened through `document === null`.
 *
 * @returns `{ path, document, error }`; `error` is a human-readable reason.
 */
export function readStoredSettings() {
  const path = settingsFilePath()
  let text
  try {
    text = readFileSync(path, 'utf8')
  } catch (error) {
    return { path, document: null, error: error?.code === 'ENOENT' ? null : errorMessage(error) }
  }
  let parsed
  try {
    parsed = JSON.parse(text)
  } catch (error) {
    return { path, document: null, error: `not valid JSON (${errorMessage(error)})` }
  }
  if (!isPlainObject(parsed)) {
    return { path, document: null, error: 'not a JSON object' }
  }
  return { path, document: parsed, error: null }
}

/**
 * Write the settings file atomically.
 *
 * A temp file plus `rename` in the same directory, so a reader never sees a
 * half-written document: the GET route reads this file on every request and a
 * truncated read would surface as "corrupt settings" in the page.
 *
 * @throws when the directory or file cannot be written; the caller decides how
 *   to report it (the route answers 500, `apply()` logs and carries on).
 */
export function writeStoredSettings(document) {
  const path = settingsFilePath()
  const dir = dirname(path)
  mkdirSync(dir, { recursive: true })
  const temp = `${path}.tmp`
  writeFileSync(temp, `${JSON.stringify(document, null, 2)}\n`, 'utf8')
  renameSync(temp, path)
  return path
}

/**
 * The keys the settings page owns, in one place.
 *
 * Two groups: the load-time config this module reads (`KNOWN_CONFIG_KEYS`) plus
 * the project-side defaults it only stores (`PROJECT_DEFAULT_KEYS`).
 * `skillFile` is deliberately absent from both: the page has no control for it,
 * and a write must not drop it from a hand-edited file (unknown keys are
 * preserved, see `sanitizeSettings`).
 *
 * This list is a **gate**, not a description: `sanitizeSettings` coerces exactly
 * the keys named here and rejects an unusable value (a `mode` outside `MODES`, a
 * non-boolean `verbose`, an unknown language). A key dropped from the list does
 * not merely lose that check — the write path would then store whatever the body
 * carried, so `PROJECT_DEFAULT_KEYS` staying here is what keeps the page's three
 * project defaults validated even though the plugin never reads them.
 */
export function knownSettingsKeys() {
  return [...KNOWN_CONFIG_KEYS, ...PROJECT_DEFAULT_KEYS]
}

/** A value the page may store for one key, or `undefined` when it is rejected. */
function coerceSetting(key, value) {
  if (key === 'guidelinesEnabled' || key === 'modelInvocable'
    || key === 'userInvocable' || key === 'verbose') {
    return typeof value === 'boolean' ? value : undefined
  }
  if (key === 'guidelinesLanguage') {
    // Only 'en' is meaningful; anything else keeps the Chinese default, so a
    // rejected value stores nothing rather than a spelling that means nothing.
    if (value === 'en' || value === 'zh') return value
    return undefined
  }
  if (key === 'mode') {
    return typeof value === 'string' && MODES.includes(value) ? value : undefined
  }
  // Path and name fields. An empty string is accepted and means "use the
  // default" — the page tells the user so, and `stringOr`/`resolveSkillDir`
  // already treat it that way.
  if (typeof value === 'string' && value.length <= 1024) return value
  return undefined
}

/**
 * Project a request body onto the settings document to store.
 *
 * Unknown keys present in `previous` are preserved rather than dropped: the
 * file is hand-editable, and silently deleting a line someone added by hand is
 * a worse failure than keeping a key this plugin does not read. Keys the body
 * does not mention are left at their previous value, so a partial write is a
 * patch rather than a replacement.
 *
 * @returns the document to write, or a `{ error }` describing the first
 *   rejected value.
 */
export function sanitizeSettings(body, previous = {}) {
  if (!isPlainObject(body)) return { error: 'the request body must be a JSON object' }
  const document = isPlainObject(previous) ? { ...previous } : {}
  const known = knownSettingsKeys()
  for (const [key, value] of Object.entries(body)) {
    if (!known.includes(key)) {
      // Not stored, and not an error either: a page newer than this file is a
      // normal upgrade state, and dropping the whole save over it is worse.
      document[key] = value
      continue
    }
    const coerced = coerceSetting(key, value)
    if (coerced === undefined) {
      return { error: `"${key}" is not a valid ${key === 'mode' ? `mode (${MODES.join('/')})`
        : key === 'guidelinesLanguage' ? "language ('zh'/'en')"
          : 'value'}` }
    }
    document[key] = coerced
  }
  return { document }
}

/* -------------------------------------------------------------------------- */
/* settings route                                                             */
/* -------------------------------------------------------------------------- */

/**
 * Read a whole request body, refusing anything over `limit` bytes.
 *
 * @returns `{ text }`, or `{ error, status }` for a body that must be answered
 *   with an error. The stream is consumed either way, so the connection is not
 *   left with unread data.
 */
async function readBody(req, limit) {
  const chunks = []
  let size = 0
  for await (const chunk of req) {
    const buffer = typeof chunk === 'string' ? Buffer.from(chunk, 'utf8') : chunk
    size += buffer.length
    if (size > limit) return { error: `request body exceeds ${limit} bytes`, status: 413 }
    chunks.push(buffer)
  }
  return { text: Buffer.concat(chunks).toString('utf8') }
}

/** One JSON response, with the headers a settings fetch needs. */
function sendJson(res, status, payload) {
  const body = `${JSON.stringify(payload, null, 2)}\n`
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body, 'utf8'),
    // The page must never show a cached document after a save.
    'cache-control': 'no-store',
  })
  res.end(body)
}

/**
 * The settings route handler.
 *
 * `GET` reports what is on disk plus what the plugin will actually use;
 * `POST` validates and stores a document; anything else is 405. Exported and
 * built from a logger rather than from `ctx`, so the tests can drive it with a
 * fake `req`/`res` — a route registered inside an effect is otherwise only
 * reachable through a live HTTP server.
 *
 * The report is in four parts, and the split between the middle two is the
 * contract: `settings` is the document on disk (what the page edits), `effective`
 * is only what `apply()` reads, and `projectDefaults` is what the page stores for
 * a project that does not exist yet — marked as not applied by this plugin.
 *
 * @param logger - `(level, message) => void`, for a write that failed.
 */
export function createSettingsRouteHandler(logger = () => {}) {
  return async function handleSettingsRoute(req, res) {
    const method = String(req?.method ?? 'GET').toUpperCase()
    if (method === 'GET' || method === 'HEAD') {
      const stored = readStoredSettings()
      if (stored.error !== null) logger('warn', `worklog: settings file is unusable: ${stored.error}`)
      const document = stored.document ?? {}
      sendJson(res, 200, {
        path: stored.path,
        // What is on disk, and what those values will be read as. The page
        // edits the first and shows the second, so a blank field is visibly
        // "back to the default" rather than invisibly so.
        settings: document,
        effective: effectiveSettings(document),
        // Stored but NOT resolved: seeds for a new project's own `.config.json`.
        // Kept apart from `effective` so the page cannot render them as "what the
        // plugin will do", and marked so a reader of this JSON — who may not have
        // this file — does not have to guess which group is which.
        projectDefaults: projectDefaults(document),
        error: stored.error,
      })
      return
    }
    if (method !== 'POST') {
      res.writeHead(405, { allow: 'GET, HEAD, POST', 'cache-control': 'no-store' })
      res.end()
      return
    }

    let read
    try {
      read = await readBody(req, SETTINGS_BODY_LIMIT)
    } catch (error) {
      sendJson(res, 400, { error: `could not read the request body: ${errorMessage(error)}` })
      return
    }
    if (read.error !== undefined) {
      sendJson(res, read.status, { error: read.error })
      return
    }

    let body
    try {
      body = JSON.parse(read.text === '' ? '{}' : read.text)
    } catch (error) {
      sendJson(res, 400, { error: `the request body is not valid JSON: ${errorMessage(error)}` })
      return
    }

    const stored = readStoredSettings()
    const sanitized = sanitizeSettings(body, stored.document ?? {})
    if (sanitized.error !== undefined) {
      sendJson(res, 400, { error: sanitized.error })
      return
    }

    let path
    try {
      path = writeStoredSettings(sanitized.document)
    } catch (error) {
      logger('error', `worklog: could not write the settings file: ${errorMessage(error)}`)
      sendJson(res, 500, { error: `could not write the settings file: ${errorMessage(error)}` })
      return
    }
    sendJson(res, 200, {
      path,
      settings: sanitized.document,
      effective: effectiveSettings(sanitized.document),
      // Same shape as GET: the page re-reads its state from this response, so a
      // field that only GET carried would go blank after every save.
      projectDefaults: projectDefaults(sanitized.document),
    })
  }
}

/**
 * Mount the settings route once `webServer` exists.
 *
 * Not declared in `inject`: a DSH build without a web server (headless, a test
 * profile) must still activate and mount its skills, and `inject` would make
 * the whole plugin wait for — or fail on — a service it only needs for the
 * settings page. `ctx.get` is the optional lookup.
 *
 * `webServer` can also arrive AFTER activation (the loader does not defer a
 * plugin for an undeclared dependency), so this polls briefly. The attempt
 * budget is finite: an embedder that never provides one is a settled fact, not
 * something to keep a timer alive for.
 *
 * The returned cleanup releases the route AND the timer. Releasing the route is
 * not optional: the registry throws on a duplicate `(kind, path)`, so a plugin
 * reload that left the route behind would fail activation outright.
 *
 * @returns a disposer, for `ctx.effect`.
 */
export function mountSettingsRoute(ctx, logger = () => {}) {
  const handler = createSettingsRouteHandler(logger)
  let routeDisposer = null
  let timer = null
  let attempts = 0
  const REGISTER_ATTEMPTS = 20
  const REGISTER_INTERVAL_MS = 500

  /** Look up the web server without letting a throwing service accessor escape. */
  function webServer() {
    let service = null
    try {
      service = typeof ctx?.get === 'function' ? ctx.get('webServer') : null
    } catch {
      service = null
    }
    if (service === null || service === undefined) {
      try {
        service = ctx?.webServer ?? null
      } catch {
        service = null
      }
    }
    return service
  }

  /** @returns whether the route is registered now. */
  function registerNow() {
    const service = webServer()
    if (service === null || typeof service.register !== 'function') return false
    routeDisposer = service.register({
      kind: 'exact',
      path: SETTINGS_ROUTE_PATH,
      handler,
    })
    return true
  }

  if (!registerNow()) {
    timer = setInterval(() => {
      attempts += 1
      if (registerNow() || attempts >= REGISTER_ATTEMPTS) {
        clearInterval(timer)
        timer = null
      }
    }, REGISTER_INTERVAL_MS)
    // A timer must not hold the process open on its own.
    if (typeof timer?.unref === 'function') timer.unref()
  }

  return () => {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
    if (routeDisposer !== null) {
      try {
        routeDisposer()
      } catch (error) {
        logger('warn', `worklog: releasing the settings route failed: ${errorMessage(error)}`)
      }
      routeDisposer = null
    }
  }
}

/**
 * Resolve the options `apply()` reads, from a settings document.
 *
 * **Every key returned here is read at mount.** That is the whole contract of
 * this function, and the reason the project-side defaults
 * (`container`/`lessons`/`mode`) must not be added to it: they are stored for the
 * page and read by `journal.py` from a project's own `.config.json`, so listing
 * them here would make the route claim this plugin honours values it never looks
 * at. `tests/audit-settings.mjs` pins the absence, including for a document that
 * does state them.
 *
 * The route reports these so the page can show what the plugin will do, and
 * `apply()` uses the same coercion through its own merge of the row config —
 * two readers of one rule, which is the only way "what the page shows" and
 * "what the plugin does" cannot drift.
 *
 * `skillFile` is part of the read surface even though the settings page has no
 * control for it (see `knownSettingsKeys`), because the question this function
 * answers is "what will the plugin read", not "what may the page write".
 */
export function effectiveSettings(document) {
  const raw = isPlainObject(document) ? document : {}
  return {
    skillDir: stringOr(raw.skillDir, DEFAULT_SKILL_DIR),
    skillFile: stringOr(raw.skillFile, SKILL_FILE),
    modelInvocable: boolOr(raw.modelInvocable, true),
    userInvocable: boolOr(raw.userInvocable, true),
    verbose: boolOr(raw.verbose, false),
    guidelinesEnabled: boolOr(raw.guidelinesEnabled, true),
    guidelinesDir: stringOr(raw.guidelinesDir, DEFAULT_GUIDELINES_DIR),
    guidelinesLanguage: raw.guidelinesLanguage === 'en' ? 'en' : 'zh',
  }
}

/**
 * The project-side defaults: stored and reported, never resolved.
 *
 * `container`, `lessons` and `mode` describe the project's own
 * `<container>/.config.json`, which `journal.py` reads. This module keeps them on
 * the page's behalf and reads none of them, so they belong here rather than in
 * `effectiveSettings()` — a key in that object is a claim that the plugin acts on
 * it.
 *
 * `appliedByPlugin` is a literal `false`, deliberately not computed from
 * anything: there is no runtime fact to consult (this module simply reads none of
 * these keys), and a marker derived from some other value could drift while still
 * looking authoritative. It is what the page's "(not read by the plugin)" label
 * is conditioned on, so the caveat comes from the route rather than from the
 * client asserting something on its own.
 */
export function projectDefaults(document) {
  const raw = isPlainObject(document) ? document : {}
  return {
    appliedByPlugin: false,
    values: {
      // The fallbacks mirror the values `coerceSetting` accepts for these keys: a
      // value it rejects is never stored through the page, so a hand-edited file
      // is the only way to arrive here with something unusable.
      container: stringOr(raw.container, DEFAULT_CONTAINER),
      lessons: stringOr(raw.lessons, DEFAULT_LESSONS),
      mode: typeof raw.mode === 'string' && MODES.includes(raw.mode) ? raw.mode : MODES[0],
    },
  }
}

/**
 * Merge the three configuration layers into one object.
 *
 * @param stored - the settings document (may be `{}`).
 * @param row - the row config from the bundle patch.
 * @param warn - reports a key this plugin does not understand.
 */
function mergeSettings(stored, row, warn) {
  const file = isPlainObject(stored) ? stored : {}
  const merged = { ...row }
  for (const [key, value] of Object.entries(file)) {
    // A stored key only wins when the file actually states it. `undefined` is
    // not a JSON value, so this only matters for a hand-built object.
    if (value !== undefined) merged[key] = value
  }
  // Unknown keys are reported for both layers: a typo in the settings file is
  // just as invisible otherwise as one in the patch.
  const unknown = Object.keys(merged).filter((key) => !KNOWN_CONFIG_KEYS.includes(key))
  if (unknown.length > 0) warn(unknown)
  return merged
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
 *
 * These are **load-time** options: they are read here, once, at mount. A change
 * made on the settings page therefore needs a host restart, which the page says
 * outright — reading them per load instead would make the page look instant and
 * the behaviour unrelated to it.
 */
export function apply(ctx, config = {}) {
  trace('apply', `enter hasSkills=${typeof ctx?.skills?.registerProvider === 'function'}`)
  const row = config !== null && typeof config === 'object' && !Array.isArray(config) ? config : {}

  // The settings page's values sit above the row config: the bundle patch
  // declares most of these keys outright, so if the row won the page could
  // never change anything.
  const stored = readStoredSettings()
  if (stored.error !== null) {
    log(ctx, 'warn', `worklog: ignoring the settings file (${toSlashes(stored.path)}): ${stored.error}`)
  }
  const merged = mergeSettings(stored.document, row, (keys) => {
    log(ctx, 'warn', `worklog: ignoring unsupported config keys: ${keys.join(', ')}`)
  })

  // Every option this mount reads, resolved by the same function the route
  // reports as `effective` — one rule with two readers, so "what the page shows"
  // and "what the plugin does" cannot drift. `skillFile` is in there even though
  // the settings page has no control for it: the page's write surface
  // (`knownSettingsKeys`) and the module's read surface are different questions.
  const options = effectiveSettings(merged)

  // Serving the settings page is the plugin's secondary job; mounting the
  // skills is the primary one. An effect keeps the route's lifetime tied to the
  // plugin's, and the disposer it returns is what stops a reload from tripping
  // the registry's duplicate-route check.
  //
  // The `else` branch is for a context with no `effect` at all (a hand-built
  // harness, not a Cordis one). It registers the route and deliberately drops
  // the disposer: with no lifecycle to hang cleanup on, there is no unload for
  // it to leak across, and refusing to register would only break the page in a
  // composition that is otherwise fine.
  if (typeof ctx?.effect === 'function') {
    ctx.effect(
      () => mountSettingsRoute(ctx, (level, message) => log(ctx, level, message)),
      'worklog: settings route',
    )
  } else {
    mountSettingsRoute(ctx, (level, message) => log(ctx, level, message))
  }
  trace('apply', `settings-file=${settingsFilePath()} settings-error=${stored.error ?? 'none'}`)

  /**
   * Mount one bundle. Fails loudly when its instruction file is missing: a
   * provider that only ever returned an empty catalog would look identical to
   * "this skill was never installed".
   */
  function mount({ providerName, label, dir, file }) {
    let raw
    try {
      raw = readFileSync(file, 'utf8')
    } catch (error) {
      // Name the failing thing and how it was resolved. A bare `ENOENT … SKILL.md`
      // cannot be acted on, because the two ways to reach this — a typo in the row
      // config, or a package whose bundle was not published — look identical.
      const reason = error?.code === 'ENOENT' ? 'not found' : errorMessage(error)
      log(ctx, 'error',
        `worklog: skill bundle "${providerName}" ${reason}: ${toSlashes(file)}`
        + ` (bundle directory ${toSlashes(dir)}, resolved from config "skillDir" or its default)`
        + '; this skill will not be available')
      trace('apply', `probe-error=${reason} provider=${providerName} file=${file}`)
      return
    }

    let probe
    try {
      probe = parseSkillFrontmatter(raw, file)
    } catch (error) {
      const reason = reasonOf(error, file)
      log(ctx, 'error', `worklog: invalid skill bundle ${toSlashes(file)}: ${reason}`)
      trace('apply', `probe-error=${reason} provider=${providerName} file=${file}`)
      return
    }

    if (probe.unknown.length > 0) {
      log(ctx, 'warn', `worklog: ignoring unsupported frontmatter keys: ${probe.unknown.join(', ')}`)
    }

    // Same rule as the logger: report and stop rather than throw. `skills` is
    // declared in `inject`, so a missing registry is a composition fault, not
    // something this plugin can fix — but a typed message naming the skill that
    // could not be served is more useful than a stack trace through `mount`.
    if (typeof ctx?.skills?.registerProvider !== 'function') {
      log(ctx, 'error',
        `worklog: cannot register skill "${probe.name}" — ctx.skills.registerProvider is not `
        + `available (is @deepseek-ai/dsh-skill mounted?); this skill will not be available`)
      trace('apply', `no-registry skill=${probe.name} type=${typeof ctx?.skills?.registerProvider}`)
      return
    }

    ctx.skills.registerProvider((control) =>
      createProvider({ providerName, label, dir, file, options, ctx }))
    trace('apply', `registered provider=${providerName} skill=${probe.name} file=${file}`)
    if (options.verbose) {
      log(ctx, 'info', `worklog: serving skill "${probe.name}" from ${file}`)
    }
  }

  const dir = resolveSkillDir(options.skillDir)
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
    const guidelinesDir = resolveSkillDir(options.guidelinesDir)
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
