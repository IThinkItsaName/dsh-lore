/**
 * dsh-lore — 插件配置卡片（浏览器半边）。
 *
 * 这是一个**手写的普通 JavaScript 文件**，没有构建步骤：包装格式取自
 * `packages/client/tsdown.client.ts` 的 banner/intro/footer，中间是普通代码。
 * 用 `React.createElement` 而不是 JSX —— JSX 需要转译，那等于引入一个构建步骤。
 *
 * `factory(require)` 的 `require` **不是** Node 的 require，而是 DSH 浏览器模块
 * 加载器注入的查找函数。它能解析的**只有**九项（权威清单见
 * `packages/client/web/src/seed.ts`）：react / react/jsx-runtime / react-dom /
 * react-dom/client / @deepseek-ai/cordis / @deepseek-ai/dsh-client-store /
 * @deepseek-ai/dsh-client-ui-slots / @deepseek-ai/dsh-client-ui-primitives /
 * @deepseek-ai/dsh-client-ui-dockkit。本文件只用到 `react` 与
 * `@deepseek-ai/dsh-client-ui-primitives`；其余一概从 `ctx` 取服务。
 *
 * ── 事实源与界面（2026-09-29 起）────────────────────────────────────────────
 *
 * 配置的**读写走官方通道**：宿主把每个带 `.volatile()` 字段的插件投影成一个设置
 * 命名空间（`dsh-settings`），浏览器侧由 `ctx.configForms` 提供按 namespace 取的
 * 表单控制器（`getSnapshot` / `subscribe` / `set` / `unset` / `mutate`）与
 * `whileServed` 门控；写回由 `dsh-config-editor` 落到**本 profile 的
 * `cordis.patch.yml`**。
 *
 * 这一页**没有自己的读写通道**，也不发任何 HTTP 请求：全部是 `ctx.configForms`。
 *
 * ── 为什么按 schema 认领自己，而不是写死 id ─────────────────────────────────
 *
 * namespace 的 id 就是 `entry.options.id`（宿主 `dsh-settings/lib/index.js:432`），
 * 而它是**部署相关**的：本机是 `include:dsh-lore`，换个挂法就变。写死必然在
 * 别的 profile 上静默失效。投影 schema 只含 `.volatile()` 字段，于是
 * "我们那十一个字段齐了"就是指纹（`FORM_FIELDS`）。
 *
 * ── 槽位：`plugins.bundle.config`，不是 `plugins.item` ──────────────────────
 *
 * 卡片挂在**本 bundle 自己那一页**上：`plugins.bundle.config`，`key` = **本包的包名**。
 * 插件管理页就是这么寻址的 —— `configured: ledger.bundles.has(openPkg.name)`
 * （`dsh-client-ui-plugin-manager/lib/client.js:3545`），渲染在 bundle 页的描述与行列表之间
 * （同文件 `:2527`）。官方那支 `@deepseek-ai/dsh-experimental-voice-input-bundle`
 * 与同为本工作区作物的 `dsh-ds-balance` 都挂在这里。
 *
 * **第一版挂错了槽**：挂了 `plugins.item`，于是它出现在插件页的**官方**那一组里。那个槽位的
 * 说明写得很清楚 —— *"One **official** plugin the Plugins page lists in its **Official group**"*，
 * 它的 catalog 还写了一句当时没照做的话：*"a bundle's configuration belongs in
 * `plugins.bundle.config` or `plugins.row.config` instead"*。我们是 bundle，不是宿主侧官方插件。
 * （教训：槽位文档里的 purpose/catalog 就是契约，选槽位前先读它，而不是照着"哪个官方插件
 * 长得像"去类比。）
 *
 * 挂载用 `whileServed` 的等价写法：命名空间在镜像里出现才挂卡片，消失就撤掉。
 *
 * ── 一页、两组、八个控件（2026-10-21 精简）──────────────────────────────────
 *
 * 上一版分三个页签（技能 / 记忆 / 诊断），页脚还有「设置位置 + 路径」和一段兼容性说明。
 * 用户的原话是"去掉无意义内容，使其尽量精简"：三个页签装八个开关，页签本身就是搬运成本；
 * 诊断页只有一个开发开关；「当前状态」是工作区数/待收/索引字数这类调试数字；「设置位置」
 * 是排查信息 —— 这些都不属于"设置"。
 *
 * 现在是一页两段：**技能**（三个开关）与**记忆**（四个开关 + 一个路径框），每个控件一句话说明，
 * 底部一行"即时生效"。
 *
 * `Config` 的十一个字段**一个都没删**：界面不渲染的 `skillDir` / `skillFile` / `verbose`
 * 仍然可用 profile patch 配置。界面只是不再给它们控件 —— 删字段会改变认领指纹，
 * 让已部署的卡片当场消失。
 *
 * ── 这一页只管插件自己的配置 ────────────────────────────────────────────────
 *
 * 项目级的 `container` / `lessons` / `mode` 不在这一页，也不该在：它们描述的是某个
 * 项目自己的 `<容器>/.config.json`，由 `journal.py config` 改。两个设置面不许管同
 * 一件事，是这套设计里唯一不许破的规则（见 `docs/settings-spec.md` §零）。
 */
window.__ModuleLoader__.load({
  id: 'dsh-lore',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports

    /** 卡片需要 React（与内置设置页共用同一份实例）。 */
    const React = require('react')
    /** 现成的基础控件：开关、文本输入。 */
    const primitives = require('@deepseek-ai/dsh-client-ui-primitives')
    const { Switch, Input } = primitives

    const h = React.createElement
    const { useCallback, useState } = React

    /** locale 命名空间：只属于这个插件。 */
    const SETTINGS_NS = 'dsh-lore.settings'
    /**
     * `plugins.bundle.config` 的 key：**本包的包名**。
     *
     * 与设置 namespace 不同，这个不是部署相关的 —— 插件管理页按 bundle 的包名寻址
     * （`ledger.bundles.has(openPkg.name)`），而"我们叫什么"由本包的 `package.json` 决定。
     */
    const BUNDLE_KEY = 'dsh-lore'

    /**
     * 认领 namespace 用的**指纹**：`Config` 里那十一个 `.volatile()` 字段的名字。
     *
     * 宿主投影时只保留 `.volatile()` 字段（`dsh-settings/lib/types/schema.js` 的
     * `volatileForm`），所以一个命名空间的 schema 同时带齐这些键，就只可能是我们。
     * **改 `lib/index.js` 的 `Config` 就必须同步改这里**（少一个 → 认领失败 →
     * 卡片不出现；多一个 → 永远认领不到）。`tests/audit-client-runtime.mjs` 从
     * `lib/index.js` 的源码里再解析一遍 `Config` 来对账，不靠这句注释。
     *
     * 注意：这里比页面上渲染的控件多三个（`skillDir` / `skillFile` / `verbose`）——
     * 认领要看 Config，不看界面。界面收敛不影响指纹。
     */
    const FORM_FIELDS = [
      'skillDir', 'skillFile', 'skillEnabled', 'modelInvocable', 'userInvocable', 'verbose',
      'memoryEnabled', 'memoryInjectIndex', 'memoryPersonalSearchable', 'memoryDir',
      'sessionsCrossWorkspace',
    ]

    const DICT_ZH = {
      'summary': '项目工作记录技能 + 全局记忆：技能开关、调用许可与记忆开关。',
      'section.skills': '技能',
      'section.memory': '记忆',
      'skillEnabled.label': '启用工作记录技能',
      'skillEnabled.hint': '关闭后不再登记 `project-work-log` 技能；记忆与记忆工具不受影响。',
      'modelInvocable.label': '允许模型自动调用',
      'modelInvocable.hint': '关闭后模型不会自己调用这个技能，你仍可以手动调用。',
      'userInvocable.label': '允许手动调用',
      'userInvocable.hint': '关闭后这个技能不再出现在可手动调用的清单里。',
      'memoryEnabled.label': '启用全局记忆',
      'memoryEnabled.hint': '关闭后索引不注入，记忆工具会明确答复它被关掉了；改完即时生效。',
      'memoryInjectIndex.label': '默认注入记忆索引',
      'memoryInjectIndex.hint': '把与本工作区相关的索引（只有 id 与一句话）放进提示词。',
      'memoryPersonalSearchable.label': '个人目录可被检索',
      'memoryPersonalSearchable.hint': '默认关闭：`personal/` 下的内容不进索引，也不会被检索返回。',
      'sessionsCrossWorkspace.label': '允许跨工作区查看会话',
      'sessionsCrossWorkspace.hint': '关闭后 `sessions` 只能查本工作区；发送本来就只到工作区粒度。',
      'memoryDir.label': '记忆存放位置',
      'memoryDir.hint': '留空 = 主目录下的 `dsh-lore-memory`。保存时会同时写进插件设置文件 —— '
        + '`journal.py` 是另一个进程，只有这样才能读同一个根。',
      'memoryDir.placeholder': '留空 = <主目录>/dsh-lore-memory',
      'path.overridden': '已覆盖',
      'path.reset': '恢复默认',
      'state.pending': '正在保存…',
      'state.saved': '已保存',
      'state.rejected': '保存失败：宿主拒绝了这次修改（可能有人同时改了同一项，重试一次）',
      'state.error': '保存失败',
      'state.unavailable': '配置暂时不可用 —— 宿主还没把这一项的设置投影出来。',
      'effect.all': '所有设置**即时生效**（用到时现读）。',
    }

    /** 英文词典。键集必须与中文完全一致（`tests/audit-client.mjs` 对账）。 */
    const DICT_EN = {
      'summary': 'The project work-log skill plus global memory: skill switches and memory switches.',
      'section.skills': 'Skills',
      'section.memory': 'Memory',
      'skillEnabled.label': 'Enable the work-log skill',
      'skillEnabled.hint': 'Off: `project-work-log` is no longer registered; memory and the memory '
        + 'tool are unaffected.',
      'modelInvocable.label': 'Let the model call this skill',
      'modelInvocable.hint': 'Off: the model will not call it on its own; you can still call it '
        + 'yourself.',
      'userInvocable.label': 'Let you call this skill',
      'userInvocable.hint': 'Off: it no longer appears in the list of skills you can invoke '
        + 'yourself.',
      'memoryEnabled.label': 'Enable global memory',
      'memoryEnabled.hint': 'Off: nothing is injected and the memory tool answers that it is off '
        + '(it stays registered). Takes effect immediately.',
      'memoryInjectIndex.label': 'Inject the memory index by default',
      'memoryInjectIndex.hint': 'Puts the index lines relevant to this workspace (id and one line '
        + 'each) into the prompt.',
      'memoryPersonalSearchable.label': 'Let search reach the personal directory',
      'memoryPersonalSearchable.hint': 'Off by default: nothing under `personal/` enters the index '
        + 'or is returned by a search.',
      'sessionsCrossWorkspace.label': 'Allow viewing sessions across workspaces',
      'sessionsCrossWorkspace.hint': 'Off: `sessions` lists this workspace only. Sending stays '
        + 'workspace-level either way.',
      'memoryDir.label': 'Memory location',
      'memoryDir.hint': 'Blank = `dsh-lore-memory` under your home directory. Saving also writes it '
        + 'into the plugin settings file — `journal.py` is a separate process, and that is the only '
        + 'way both read the same root.',
      'memoryDir.placeholder': 'Blank = <home>/dsh-lore-memory',
      'path.overridden': 'Overridden',
      'path.reset': 'Reset',
      'state.pending': 'Saving…',
      'state.saved': 'Saved',
      'state.rejected': 'Save failed: the host refused this change (someone may have changed the '
        + 'same field — try again)',
      'state.error': 'Save failed',
      'state.unavailable': 'Configuration is unavailable — the host has not projected this '
        + 'entry\'s settings yet.',
      'effect.all': 'Every setting here takes effect **immediately** (read when used).',
    }

    /* ---------------------------------------------------------------- 样式 --
     * 只用 `--dsw-*` token 和行内样式，不自带 CSS 文件。 */
    const S = {
      root: { display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '760px', color: 'var(--dsw-alias-label-primary)' },
      section: { display: 'flex', flexDirection: 'column' },
      /* 分段标题：比正文小一号、字重 500、全大写式的视觉分组，不再用页签。 */
      sectionTitle: {
        margin: 0, padding: '0 0 4px', fontSize: '12px', lineHeight: '18px', fontWeight: 500,
        letterSpacing: '0.04em', textTransform: 'uppercase',
        color: 'var(--dsw-alias-label-tertiary)',
      },
      /* 字段行 = 官方设置页的 chrome：标签在左、控件在右、分隔线在行下。 */
      row: {
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: '24px', padding: '14px 0',
        borderBottom: '0.5px solid var(--dsw-alias-border-l2)',
      },
      rowLast: { borderBottom: 'none' },
      /* 需要整行说明的字段（记忆存放位置）：标签与说明占一行，控件另起一行、占满宽度。 */
      rowStacked: { flexDirection: 'column', alignItems: 'stretch', gap: '8px' },
      labelBlock: { display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0 },
      control: { display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' },
      controlStacked: { display: 'flex', flexDirection: 'column', alignItems: 'stretch', gap: '4px', width: '100%' },
      label: { fontSize: '14px', lineHeight: '20px' },
      hint: { margin: 0, fontSize: '12px', lineHeight: '18px', color: 'var(--dsw-alias-label-secondary)' },
      effective: { fontSize: '12px', color: 'var(--dsw-alias-label-tertiary)' },
      linkButton: {
        font: 'inherit', fontSize: '12px', color: 'var(--dsw-alias-label-secondary)',
        background: 'none', border: 0, padding: 0, cursor: 'pointer',
        textDecoration: 'underline', marginLeft: '6px',
      },
      status: { fontSize: '12px', color: 'var(--dsw-alias-label-secondary)' },
      statusError: { fontSize: '12px', color: 'var(--dsw-alias-label-error)' },
      note: { margin: 0, fontSize: '12px', color: 'var(--dsw-alias-label-tertiary)' },
    }

    /* -------------------------------------------------- 认领 namespace ---- */

    /**
     * 一个对象是否同时带齐 `FORM_FIELDS` 那十一个名字。
     *
     * 用 `hasOwnProperty` 而不是 `in`：投影是宿主现做的普通对象，原型链上没有我们的字段，
     * 而 `in` 会把 `toString` 这类名字也算命中。
     */
    function hasEveryFormField(value) {
      if (value === null || typeof value !== 'object' || Array.isArray(value)) return false
      return FORM_FIELDS.every((key) => Object.prototype.hasOwnProperty.call(value, key))
    }

    /**
     * 从设置镜像里认出**我们自己的** namespace。
     *
     * 判据只有一条：这一行的 **`value`**（宿主投影出来的**生效配置**）同时带齐
     * `FORM_FIELDS` 那十一个名字。认不出就返回 `undefined` —— 调用方据此**什么都不注册**：
     * 宁可这一页不出现，也不要在别人的 namespace 上挂一张会写错地方的卡片。
     *
     * ── 为什么读 `value` 而不是 `schema`（2026-09-29 在真实宿主上量出来的）────────────
     *
     * 上线的第一版读的是 `row.schema.properties`。**真实投影里没有这个位置**：宿主发的是
     * schemastery 的**重水合信封** `{uid, refs}`，字段名躺在 `refs[<uid>].dict` 里，
     * 客户端收下后用 `schema.rehydrate(...)` 还原。实测（把 `dsh-settings` 的
     * `volatileForm(Config).toJSON()` 跑一遍）：
     *
     *     toJSON() top-level keys : ["uid","refs"]
     *     json.properties         : UNDEFINED
     *
     * 于是那一版的判据在真机上**恒为假**，卡片一次都没注册过；而当时的 harness 用
     * `{type:'object', properties:{…}}` 造假行 —— **照着代码的假设去造假宿主**，所以 151 条
     * 断言全绿。这是本项目第三次栽在同一个坑里（`0016` 量错对象、`0041` 假 editor 抹平层级）。
     *
     * 现在改用 `value`：它是**普通 JSON**，就是宿主解析后的那份配置（十一个字段都有 schema
     * 默认值，所以恒在），不依赖 schemastery 的内部编码，也是"这一行到底是谁"最直接的答案。
     * harness 现在按**真实信封**造行，所以再退回读 `schema` 会当场变红。
     *
     * 纯函数，导出只为可测（`tests/audit-client-runtime.mjs` 用对抗性输入直接打它）。
     *
     * @param mirror - `ctx.configForms.describe()` 返回的镜像（`getSnapshot()`）。
     * @returns 认领到的 namespace 字符串，或 undefined。
     */
    function claimNamespace(mirror) {
      const view = typeof mirror?.getSnapshot === 'function' ? mirror.getSnapshot()?.view : undefined
      const rows = Array.isArray(view?.namespaces) ? view.namespaces : []
      for (const row of rows) {
        if (!hasEveryFormField(row?.value)) continue
        if (typeof row.ns === 'string' && row.ns !== '') return row.ns
      }
      return undefined
    }

    /**
     * Fields that are unmistakably ours: a namespace carrying these **is** our row, one restart
     * behind. Used only by the diagnostic below — the claim itself stays strict.
     */
    const DISTINCTIVE_FIELDS = ['memoryInjectIndex', 'memoryPersonalSearchable']

    /** The last mismatch we complained about, so one situation warns once. */
    let warnedFor = ''

    /**
     * Say why the card is missing — once, and only when the row really is ours.
     *
     * The claim is strict on purpose: a namespace must carry **every** field this client knows,
     * which is what makes it unambiguous（少一个 → 认领失败；多一个 → 永远认领不到）。The price is
     * that **editing `Config` makes the card vanish until DSH restarts** — the running host still
     * projects the old schema — and that failure is completely silent: nothing throws, no log
     * line, the page simply has no card. It happened on 2026-09-30 right after `skillEnabled` was
     * added (`work_log/07-rename-070/0062`); the only symptom was「插件管理界面点进去没有东西」.
     *
     * So: keep the strict claim, drop the silence. Scoped by `DISTINCTIVE_FIELDS`, so a foreign
     * namespace (ds-balance's, the voice-input bundle's) never triggers it.
     */
    function warnAboutMissingNamespace(mirror) {
      const view = typeof mirror?.getSnapshot === 'function' ? mirror.getSnapshot()?.view : undefined
      const rows = Array.isArray(view?.namespaces) ? view.namespaces : []
      for (const row of rows) {
        const value = row?.value
        if (value === null || typeof value !== 'object') continue
        if (!DISTINCTIVE_FIELDS.every((field) => Object.prototype.hasOwnProperty.call(value, field))) continue
        const missing = FORM_FIELDS.filter((field) => !Object.prototype.hasOwnProperty.call(value, field))
        const key = `${missing.join(',')}|${Object.keys(value).length}`
        if (key === warnedFor) return
        warnedFor = key
        try {
          console.warn(
            'dsh-lore: the settings card is not showing. This client expects '
            + `${FORM_FIELDS.length} fields, but the host projects our namespace with `
            + `${Object.keys(value).length} — missing: ${missing.join(', ') || '(none)'}. `
            + 'That is the normal consequence of changing the plugin\'s Config while DSH is '
            + 'running: the host half is one restart behind. Restart DSH, then refresh the page.',
          )
        } catch {
          /* a console that refuses to warn must not break the mount */
        }
        return
      }
    }

    /* ------------------------------------------------------- 表单读数 ------ */

    /** 用户层（profile patch）里的文本；没写过就是空串。 */
    function overrideText(snapshot, key) {
      const value = snapshot?.user?.[key]
      return value === undefined || value === null ? '' : String(value)
    }

    /** 这一项在 profile 里有没有被显式写过（决定"已覆盖 / 恢复默认"出不出现）。 */
    function isOverridden(snapshot, key) {
      const user = snapshot?.user
      return user !== null && typeof user === 'object'
        && Object.prototype.hasOwnProperty.call(user, key)
    }

    /** 生效值（含 schema 默认与下层配置）。布尔项直接用它渲染开关。 */
    function effectiveValue(snapshot, key, fallback) {
      const value = snapshot?.value?.[key]
      return value === undefined || value === null ? fallback : value
    }

    /** 留空时实际会用到的那个值：下层（包内/组合）优先，没有就用生效值。 */
    function inheritedText(snapshot, key) {
      const base = snapshot?.base?.[key]
      const value = base === undefined || base === null ? snapshot?.value?.[key] : base
      return value === undefined || value === null ? '' : String(value)
    }

    /**
     * 写失败的原因**要出声**（2026-10-15 补）。
     *
     * 与本文件 `warnAboutMissingNamespace()` 是同一条信条：界面只留一句通用的「出错」，
     * 控制台里必须留下字段名与原始错误 —— 否则用户来报案时，我们手里一个字节的证据都没有。
     * 通知文案本身不改（那是给用户看的），这里补的是给排查用的那一半。
     */
    function reportWriteFailure(field, error) {
      try {
        console.warn(`dsh-lore: writing \`${field}\` failed`, error)
      } catch {
        /* a console that refuses to warn must not break the card */
      }
    }

    /* ------------------------------------------------------------ 行 ------ */

    /** 一行"标签 + 说明"在左、控件在右。 */
    function row({ t, labelKey, hintKey, control, last = false }) {
      return h('div', { style: last ? { ...S.row, ...S.rowLast } : S.row },
        h('div', { style: S.labelBlock },
          h('div', { style: S.label }, t(labelKey)),
          h('div', { style: S.hint }, t(hintKey))),
        h('div', { style: S.control }, control))
    }

    /* ---------------------------------------------------------- 组件 ------ */

    /**
     * 插件页上的那张卡片。
     *
     * 两种视图由插件页用 `view` 指定：`summary` 是条目上的一句话（必须返回字符串），
     * 其余是整页。**所有 hook 都在分支之前调用** —— 早返回会改变 hook 次序。
     *
     * `props` 由槽位注册的 `inject` 面注入：`hooks.form` 变成 `useForm`，另外两个
     * 是写动作（`save` / `reset`）。动作返回**是否被宿主接受**，不抛异常——被拒绝
     * （含 revision 冲突）必须说出来，这是本页最容易"看着成功其实没保存"的地方。
     */
    function WorklogCard(props) {
      const fallbackT = useCallback((key) => (DICT_ZH[key] === undefined ? key : DICT_ZH[key]), [])
      const t = typeof props?.t === 'function' ? props.t : fallbackT
      const useForm = typeof props?.useForm === 'function' ? props.useForm : () => undefined

      const snapshot = useForm((value) => value)
      const [notice, setNotice] = useState(null)
      /**
       * 文本字段的**未提交草稿**（`field -> 用户刚敲的文本`）。
       *
       * 为什么需要它：输入框的值来自设置镜像，而镜像是**宿主应答回来**才变的。
       * 不留草稿的话，用户每敲一个字符，输入框都会先被 React 按旧值重置一次 ——
       * 那是典型的受控输入丢字符/光标跳位。草稿让"用户看到的"始终是他自己敲的。
       *
       * 为什么改成**失焦/回车才写**：每次写入都会让宿主把 patch 文件原子重写一遍。
       * 逐字符写会为一次编辑产生几十次写盘（以及编辑器的备份文件）。开关是离散选择，
       * 仍然即时写 —— 只有路径框需要"敲完再提交"。
       */
      const [drafts, setDrafts] = useState({})

      /** 丢掉某一项未提交的草稿（提交成功、被拒、或点了恢复默认之后）。 */
      const clearDraft = useCallback((field) => {
        setDrafts((previous) => {
          if (!(field in previous)) return previous
          const next = { ...previous }
          delete next[field]
          return next
        })
      }, [])

      /**
       * 写一项并**如实报告结果**。
       *
       * 动作返回的是"宿主有没有接受"，不抛异常。两种失败都要落回**真实值**：
       * 被拒绝（含 revision 冲突）时清掉草稿，输入框会显示实际存着的值，而不是
       * 用户刚敲的 —— 否则页面会停在"看着保存成功了"的假象上。
       *
       * 界面上仍只有一句通用的「出错」，但**原因另交给 `reportWriteFailure()`**：
       * 不显示不等于不留痕。
       */
      const write = useCallback((field, value, mode) => {
        setNotice({ kind: 'pending' })
        let run
        try {
          run = mode === 'unset' ? props.reset(field) : props.save(field, value)
        } catch (error) {
          clearDraft(field)
          setNotice({ kind: 'error' })
          reportWriteFailure(field, error)
          return
        }
        Promise.resolve(run).then(
          (accepted) => {
            clearDraft(field)
            setNotice({ kind: accepted === false ? 'rejected' : 'saved' })
          },
          (error) => {
            clearDraft(field)
            setNotice({ kind: 'error' })
            reportWriteFailure(field, error)
          },
        )
      }, [props, clearDraft])

      if (props?.view === 'summary') return t('summary')

      const status = snapshot?.status
      const ready = status === 'ready'
      const writable = ready && snapshot?.writable !== false
      const disabled = !writable || notice?.kind === 'pending'

      const noticeText = notice === null ? null
        : notice.kind === 'pending' ? t('state.pending')
          : notice.kind === 'saved' ? t('state.saved')
            : notice.kind === 'rejected' ? t('state.rejected')
              : t('state.error')
      const noticeStyle = notice !== null && (notice.kind === 'rejected' || notice.kind === 'error')
        ? S.statusError
        : S.status

      const onSwitch = (field) => (next) => { write(field, next, 'set') }

      const switchRow = (field, last = false) => row({
        t,
        labelKey: field + '.label',
        hintKey: field + '.hint',
        last,
        control: h(Switch, {
          label: t(field + '.label'),
          checked: effectiveValue(snapshot, field, false) === true,
          disabled,
          onChange: onSwitch(field),
        }),
      })

      /**
       * 路径字段。
       *
       * 显示的是**用户层**（profile patch）的值：留空即"用下层的值"，右侧的
       * "已覆盖 / 恢复默认"只在真的覆盖过时出现。输入过程中只更新草稿（不写盘），
       * 失焦或回车才提交 —— 提交时与已存值相同就不写（省掉一次无意义的 patch 重写）。
       *
       * 占位文案的规则（2026-10-15 修过一次）：**宿主继承值优先，继承值为空时回落到
       * 这一栏自己的文案**（`inheritedText(snapshot, field) || t(field + '.placeholder')`）。
       * 原来只认继承值，于是"下层配置里没写这个目录"的部署会看到一个**空框**，
       * locale 里那两句说明就成了没人读的死键。记忆根那一栏相反：**总是**用自己的文案
       * ——它的"继承值"是用户主目录下的默认位置，说出来比空着更容易懂。
       * "看着像已保存"仍靠继承值，这条有测试钉着（`tests/audit-client-runtime.mjs`）。
       */
      const PLACEHOLDER_KEYED = new Set(['memoryDir'])
      /**
       * `stacked` —— 说明文字与输入框**各占一整行**（标签+说明在上、输入框满宽在下）。
       *
       * 为什么需要：记忆根那句说明比其他字段长（它要讲"留空用默认""相对路径按主目录算"
       * "会同步写进设置文件"三件事），跟输入框挤在同一行的左右两侧时，说明被压成一条窄柱、
       * 输入框也被挤短。用户 2026-10-14 明确要求分开。
       */
      const pathField = (field, hintKey = 'memoryDir.hint', stacked = false) => {
        const overridden = isOverridden(snapshot, field)
        const committed = overrideText(snapshot, field)
        const draft = drafts[field]
        const text = draft === undefined ? committed : draft
        const commit = () => {
          if (draft === undefined) return
          if (draft === committed) {
            clearDraft(field)
            return
          }
          write(field, draft, draft === '' ? 'unset' : 'set')
        }
        const input = h(Input, {
          id: 'dsh-lore-' + field,
          'aria-label': t(field + '.label'),
          value: text,
          placeholder: PLACEHOLDER_KEYED.has(field)
            ? t(field + '.placeholder')
            : (inheritedText(snapshot, field) || t(field + '.placeholder')),
          disabled,
          onChange: (event) => {
            const next = event.target.value
            setDrafts((previous) => ({ ...previous, [field]: next }))
          },
          onBlur: commit,
          onKeyDown: (event) => {
            if (event.key === 'Enter') commit()
          },
        })
        const overrideNote = overridden
          ? h('div', { style: S.effective, 'data-mark': t('path.overridden') },
            t('path.overridden'),
            h('button', {
              type: 'button',
              style: S.linkButton,
              disabled,
              onClick: () => {
                clearDraft(field)
                write(field, '', 'unset')
              },
            }, t('path.reset')))
          : null
        const label = h('label', { style: S.label, htmlFor: 'dsh-lore-' + field }, t(field + '.label'))
        const hint = h('div', { style: S.hint }, t(hintKey))

        if (stacked) {
          return h('div', { style: { ...S.row, ...S.rowStacked } },
            h('div', { style: S.labelBlock }, label, hint),
            h('div', { style: S.controlStacked }, input, overrideNote))
        }
        return h('div', { style: S.row },
          h('div', { style: S.labelBlock }, label, hint),
          h('div', { style: S.control }, input, overrideNote))
      }

      /* 两段。段内最后一行不带分隔线 —— 段标题已经把边界说清楚了。 */
      const sections = [
        {
          key: 'skills',
          title: t('section.skills'),
          rows: [
            switchRow('skillEnabled'),
            switchRow('modelInvocable'),
            switchRow('userInvocable', true),
          ],
        },
        {
          key: 'memory',
          title: t('section.memory'),
          rows: [
            switchRow('memoryEnabled'),
            switchRow('memoryInjectIndex'),
            switchRow('memoryPersonalSearchable'),
            switchRow('sessionsCrossWorkspace'),
            pathField('memoryDir', 'memoryDir.hint', true),
          ],
        },
      ]

      return h('div', { style: S.root },
        ready ? null : h('p', { style: S.statusError, role: 'alert' }, t('state.unavailable')),

        sections.map((section) => h('div', { key: section.key, style: S.section },
          h('h3', { style: S.sectionTitle }, section.title),
          section.rows)),

        noticeText === null ? null : h('p', { style: noticeStyle, role: 'status' }, noticeText),

        h('p', { style: S.note }, t('effect.all')))
    }

    /* ---------------------------------------------------------- 装载 ------ */

    /**
     * 客户端插件的装载。
     *
     * `inject: ['locale', 'slots', 'configForms']` —— 三者都是硬需求：没有 slots
     * 就没有挂载点，没有 locale 拿不到 `t`，没有 configForms 就没有配置读写面。
     * 它们在内置组合里都是 immediately 层，早于本插件。
     *
     * namespace **认领**发生在镜像到位之后，所以卡片是**动态挂/撤**的：镜像里出现
     * 我们的 schema 就注册，消失就撤掉（`whileServed` 的等价写法；不用它是因为
     * 它要求先知道 namespace，而我们恰恰要先从镜像里认出来）。
     */
    const inject = ['locale', 'slots', 'configForms']

    function apply(ctx) {
      const locale = ctx.locale

      // ctx.effect 会立即执行回调，并把回调返回的函数当作卸载清理。
      ctx.effect(
        () => locale.register(SETTINGS_NS, { zh: DICT_ZH, en: DICT_EN }),
        'dsh-lore: settings dictionaries',
      )

      const forms = ctx.configForms
      const mirror = forms.describe()
      /** 当前挂着的那张卡片：{ns, dispose}；没认领到时为 null。 */
      let mounted = null

      /** 为一个 namespace 挂上卡片，返回撤下它的 disposer。 */
      function mountCard(ns) {
        const form = forms.get(ns)
        return ctx.slots.inject('plugins.bundle.config', () => ctx.slots.register({
          name: 'plugins.bundle.config',
          // keyed 槽位：key 就是寻址键，没有 id / order / label 这些字段。
          key: BUNDLE_KEY,
          locale: SETTINGS_NS,
          inject: () => ({
            hooks: { form },
            save: (field, value) => form.set(field, value),
            reset: (field) => form.unset(field),
          }),
        }, WorklogCard))
      }

      function sync() {
        const ns = claimNamespace(mirror)
        if (mounted !== null && mounted.ns === ns) return
        if (mounted !== null) {
          mounted.dispose()
          mounted = null
        }
        if (ns === undefined) {
          // 认领不到 ≠ 无事发生：最可能的原因是宿主半边比客户端落后一次重启（改了 `Config`
          // 但没重启）。这里把它说出来，免得下次又只剩「点进去没有东西」这一个症状。
          warnAboutMissingNamespace(mirror)
          return
        }
        mounted = { ns, dispose: mountCard(ns) }
        warnedFor = ''
      }

      ctx.effect(() => {
        const off = mirror.subscribe(sync)
        // 镜像可能是懒的：订阅之后主动催一次，并立即按当前快照对齐一次。
        mirror.ensure()
        sync()
        return () => {
          off()
          if (mounted !== null) {
            mounted.dispose()
            mounted = null
          }
        }
      }, 'dsh-lore: plugins page card')
    }

    exports.name = 'dsh-lore'
    exports.inject = inject
    exports.apply = apply

    /**
     * 词典与认领判据也导出，**只为可测**：
     * `tests/audit-client.mjs` 对账两本词典的键集，`tests/audit-client-runtime.mjs`
     * 直接用对抗性输入打 `claimNamespace`。
     */
    exports.DICT_ZH = DICT_ZH
    exports.DICT_EN = DICT_EN
    exports.FORM_FIELDS = FORM_FIELDS
    exports.claimNamespace = claimNamespace
    return module.exports
  },
})
