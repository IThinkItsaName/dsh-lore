/**
 * dsh-worklog — 插件配置卡片（浏览器半边）。
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
 * 所以这一页**不再自带读写通道**：旧的自建 `settings.json` 路由只剩一个**只读
 * 状态端点**（记忆规模、以及设置到底落在哪），见 `STATUS_URL`。
 *
 * ── 为什么按 schema 认领自己，而不是写死 id ─────────────────────────────────
 *
 * namespace 的 id 就是 `entry.options.id`（宿主 `dsh-settings/lib/index.js:432`），
 * 而它是**部署相关**的：本机是 `include:dsh-worklog`，换个挂法就变。写死必然在
 * 别的 profile 上静默失效。投影 schema 只含 `.volatile()` 字段，于是
 * "我们那十一个字段齐了"就是指纹（`FORM_FIELDS`）。
 *
 * ── 槽位 ────────────────────────────────────────────────────────────────────
 *
 * 注册进 `plugins.item`（**插件页**的条目），与官方那几个宿主侧插件的配置卡片
 * 同构（web-search / shell / subagent / agent-loop 各有一份伴生客户端包，见
 * `dsh-client-ui-settings-web-search/lib/client.js:307`）。用 `whileServed` 的等价
 * 写法：命名空间在镜像里出现才挂卡片，消失就撤掉。
 *
 * ── 这一页只管插件自己的配置 ────────────────────────────────────────────────
 *
 * 项目级的 `container` / `lessons` / `mode` 不在这一页，也不该在：它们描述的是某个
 * 项目自己的 `<容器>/.config.json`，由 `journal.py config` 改。两个设置面不许管同
 * 一件事，是这套设计里唯一不许破的规则（见 `docs/settings-spec.md` §零）。
 */
window.__ModuleLoader__.load({
  id: 'dsh-worklog',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports

    /** 卡片需要 React（与内置设置页共用同一份实例）。 */
    const React = require('react')
    /** 现成的基础控件：开关、文本输入、分段控件、分段标签栏、折叠行。 */
    const primitives = require('@deepseek-ai/dsh-client-ui-primitives')
    const { Switch, Input, SegmentedControl, DisclosureRow, SegmentedTabs } = primitives

    const h = React.createElement
    const { useCallback, useEffect, useState } = React

    /** 只读状态端点。改这里必须同时改 `lib/index.js` 的 `STATUS_ROUTE_PATH`。 */
    const STATUS_URL = '/plugins/dsh-worklog/status.json'
    /** locale 命名空间：只属于这个插件。 */
    const SETTINGS_NS = 'dsh-worklog.settings'
    /** 插件页条目的 id 与次序。 */
    const ITEM_ID = 'dsh-worklog'
    const ITEM_ORDER = 50

    /**
     * 认领 namespace 用的**指纹**：`Config` 里那十一个 `.volatile()` 字段的名字。
     *
     * 宿主投影时只保留 `.volatile()` 字段（`dsh-settings/lib/types/schema.js` 的
     * `volatileForm`），所以一个命名空间的 schema 同时带齐这些键，就只可能是我们。
     * **改 `lib/index.js` 的 `Config` 就必须同步改这里**（少一个 → 认领失败 →
     * 卡片不出现；多一个 → 永远认领不到）。`tests/audit-client-runtime.mjs` 从
     * `lib/index.js` 的源码里再解析一遍 `Config` 来对账，不靠这句注释。
     */
    const FORM_FIELDS = [
      'skillDir', 'skillFile', 'modelInvocable', 'userInvocable', 'verbose',
      'guidelinesEnabled', 'guidelinesDir', 'guidelinesLanguage',
      'memoryEnabled', 'memoryInjectIndex', 'memoryPersonalSearchable',
    ]

    /* ------------------------------------------------------------ 三个页签 --
     * `SegmentedTabs` **只渲染标签栏，面板由调用方持有**，所以 tab 与 panel 的
     * 关联要自己连：它用 `items[].id` 当标签页的 DOM id、`items[].panelId` 当
     * `aria-controls`，面板反过来用 `aria-labelledby` 指回标签页的 id。 */
    const TAB_SKILLS = 'skills'
    const TAB_MEMORY = 'memory'
    const TAB_ADVANCED = 'advanced'
    const TAB_IDS = {
      [TAB_SKILLS]: { tabId: 'dsh-worklog-tab-skills', panelId: 'dsh-worklog-panel-skills' },
      [TAB_MEMORY]: { tabId: 'dsh-worklog-tab-memory', panelId: 'dsh-worklog-panel-memory' },
      [TAB_ADVANCED]: { tabId: 'dsh-worklog-tab-advanced', panelId: 'dsh-worklog-panel-advanced' },
    }

    const DICT_ZH = {
      'title': '工作记录',
      'summary': '项目工作记录技能 + 全局记忆：目录、语言与记忆默认值都在这里。',
      'tabs.label': '设置分组',
      'tabs.skills': '技能',
      'tabs.memory': '记忆',
      'tabs.advanced': '高级',
      'guidelinesEnabled.label': '启用可靠性准则技能',
      'guidelinesEnabled.hint': '关闭后 `reliability-guidelines` 技能不再登记，'
        + '`project-work-log` 不受影响。',
      'guidelinesLanguage.label': '准则语言',
      'guidelinesLanguage.hint': '只影响准则那一份技能；`project-work-log` 本身固定是中文。',
      'language.control': '准则语言',
      'paths.title': '路径',
      'skillDir.label': '工作记录技能目录',
      'guidelinesDir.label': '准则技能目录',
      'path.hint': '相对路径从包根目录算起；留空则用包内默认值。',
      'path.overridden': '已覆盖',
      'path.reset': '恢复默认',
      /* ── 记忆页 ─────────────────────────────────────────────────── */
      'memoryEnabled.label': '启用全局记忆',
      'memoryEnabled.hint': '关闭后索引不注入，记忆工具也不出场（调用它会明确告诉你它被关掉了）。'
        + '这是装载参数，改完需重启 DSH。',
      'memoryInjectIndex.label': '默认注入记忆索引',
      'memoryInjectIndex.hint': '把与本工作区相关的索引（只有 id 与一句话）放进提示词。'
        + '关掉则只能靠主动检索。改完即时生效。',
      'memoryPersonalSearchable.label': '个人目录可被检索',
      'memoryPersonalSearchable.hint': '默认关闭：`personal/` 下的内容不进索引，也不会被检索返回。'
        + '改完即时生效。',
      'memory.title': '当前状态',
      'memory.unknown': '未读取（需要插件在宿主侧就位后才报得出）',
      'memory.workspaces': '已登记工作区',
      'memory.inbox': '待收',
      'memory.indexChars': '索引字数',
      'memory.note': '上传许可不在这一页 —— 它在各工作区自己的 `work_log/发布.md` 里。',
      'verbose.label': '装载时打日志',
      'verbose.hint': '装载时多打一行日志：技能名与它实际读的文件。',
      'modelInvocable.label': '允许模型自动调用',
      'modelInvocable.hint': '关闭后模型不会自己调用这两个技能，你仍可以手动调用。',
      'userInvocable.label': '允许手动调用',
      'userInvocable.hint': '关闭后这两个技能不再出现在可手动调用的清单里。',
      'state.pending': '正在保存…',
      'state.saved': '已保存',
      'state.rejected': '保存失败：宿主拒绝了这次修改（可能有人同时改了同一项，重试一次）',
      'state.error': '保存失败',
      'state.unavailable': '配置暂时不可用 —— 宿主还没把这一项的设置投影出来。',
      'state.loading': '正在读取…',
      /* 重启说明**按页给**，不整页一句：只有装载期读的那些才真需要重启。 */
      'restart.skills': '这一页是装载参数：改完需重启 DSH 才生效。',
      'restart.memory': '总开关是装载参数（需重启）；另两项在用到时现读，改完即时生效。',
      'restart.advanced': '这一页是装载参数：改完需重启 DSH 才生效。',
      /* 设置落在哪：这一行是官方通道的可核对面 —— 页面自己不说，用户只能猜。 */
      'where.label': '设置位置',
      'where.config': '本 profile 的 `cordis.patch.yml`',
      'where.file': '插件自己的设置文件（本部署没有 profile 配置编辑器）',
      'where.unknown': '未读取',
      'status.loadError': '状态读取失败',
      'spec.note': '兼容性说明：',
      'scope.note': '容器目录名、经验目录名与默认精细度是项目级设置，不在这一页 —— '
        + '它们属于项目自己的 `.config.json`，用 `journal.py config` 改；'
        + '改名类字段对已有项目是破坏性的。',
    }

    /** 英文词典。键集必须与中文完全一致（`tests/audit-client.mjs` 对账）。 */
    const DICT_EN = {
      'title': 'Worklog',
      'summary': 'The project work-log skill plus global memory: directories, language and '
        + 'memory defaults all live here.',
      'tabs.label': 'Settings groups',
      'tabs.skills': 'Skills',
      'tabs.memory': 'Memory',
      'tabs.advanced': 'Advanced',
      'guidelinesEnabled.label': 'Enable the reliability-guidelines skill',
      'guidelinesEnabled.hint': 'Switching this off stops registering `reliability-guidelines`; '
        + '`project-work-log` is unaffected.',
      'guidelinesLanguage.label': 'Guidelines language',
      'guidelinesLanguage.hint': 'Affects the guidelines skill only — `project-work-log` itself '
        + 'is written in Chinese.',
      'language.control': 'Guidelines language',
      'paths.title': 'Paths',
      'skillDir.label': 'Work-log skill directory',
      'guidelinesDir.label': 'Guidelines skill directory',
      'path.hint': 'A relative path resolves from the package root; leave it blank for the '
        + 'bundled default.',
      'path.overridden': 'Overridden',
      'path.reset': 'Reset',
      /* ── memory ─────────────────────────────────────────────────── */
      'memoryEnabled.label': 'Enable global memory',
      'memoryEnabled.hint': 'Off: the index is not injected and the memory tool does not appear '
        + 'at all (calling it says plainly that it is off). This is a load-time option, so it '
        + 'needs a DSH restart.',
      'memoryInjectIndex.label': 'Inject the memory index by default',
      'memoryInjectIndex.hint': 'Puts the index lines relevant to this workspace (id and one line '
        + 'each) into the prompt. Off: reachable only by searching. Takes effect immediately.',
      'memoryPersonalSearchable.label': 'Let search reach the personal directory',
      'memoryPersonalSearchable.hint': 'Off by default: nothing under `personal/` enters the index '
        + 'or is returned by a search. Takes effect immediately.',
      'memory.title': 'Current state',
      'memory.unknown': 'not read yet (the plugin has to report it from the host side)',
      'memory.workspaces': 'registered workspaces',
      'memory.inbox': 'waiting in the inbox',
      'memory.indexChars': 'index characters',
      'memory.note': 'Upload permission is not on this page — it lives in each workspace\'s own '
        + '`work_log/发布.md`.',
      'verbose.label': 'Log at mount',
      'verbose.hint': 'Logs one extra line when the plugin mounts: the skill name and the file '
        + 'it actually reads.',
      'modelInvocable.label': 'Let the model call these skills',
      'modelInvocable.hint': 'Off: the model will not call them on its own; you can still call '
        + 'them yourself.',
      'userInvocable.label': 'Let you call these skills',
      'userInvocable.hint': 'Off: they no longer appear in the list of skills you can invoke '
        + 'yourself.',
      'state.pending': 'Saving…',
      'state.saved': 'Saved',
      'state.rejected': 'Save failed: the host refused this change (someone may have changed the '
        + 'same field — try again)',
      'state.error': 'Save failed',
      'state.unavailable': 'Configuration is unavailable — the host has not projected this '
        + 'entry\'s settings yet.',
      'state.loading': 'Loading…',
      /* Restart notes are per-panel, not one line for the whole page. */
      'restart.skills': 'This panel holds load-time options: a DSH restart is required.',
      'restart.memory': 'The master switch is a load-time option (restart needed); the other two '
        + 'are read when used, so they take effect immediately.',
      'restart.advanced': 'This panel holds load-time options: a DSH restart is required.',
      'where.label': 'Settings live in',
      'where.config': 'this profile\'s `cordis.patch.yml`',
      'where.file': 'the plugin\'s own settings file (this deployment has no profile config '
        + 'editor)',
      'where.unknown': 'not read yet',
      'status.loadError': 'Could not read the runtime status',
      'spec.note': 'Compatibility note: ',
      'scope.note': 'The container directory name, the lessons directory name and the default '
        + 'granularity are project-level settings and are not offered here — they belong to a '
        + 'project\'s own `.config.json`, changed with `journal.py config`. Rename-style fields '
        + 'are destructive to a project that already has records.',
    }

    /* ---------------------------------------------------------------- 样式 --
     * 只用 `--dsw-*` token 和行内样式，不自带 CSS 文件。 */
    const S = {
      root: { display: 'flex', flexDirection: 'column', gap: '12px', maxWidth: '760px', color: 'var(--dsw-alias-label-primary)' },
      summary: { margin: 0, fontSize: '13px', lineHeight: 1.5, color: 'var(--dsw-alias-label-tertiary)' },
      /* 字段行 = 官方设置页的 chrome：标签在左、控件在右、分隔线在行下。 */
      row: {
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: '24px', padding: '16px 0',
        borderBottom: '0.5px solid var(--dsw-alias-border-l2)',
      },
      rowLast: { borderBottom: 'none' },
      labelBlock: { display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0 },
      control: { display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' },
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
      footer: { fontSize: '12px', color: 'var(--dsw-alias-label-tertiary)' },
      code: { wordBreak: 'break-all', fontFamily: 'var(--dsw-font-family)', opacity: 0.85 },
      panel: { display: 'flex', flexDirection: 'column' },
      pathsBody: { display: 'flex', flexDirection: 'column', gap: '8px' },
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
      const [runtime, setRuntime] = useState(null)
      const [runtimeError, setRuntimeError] = useState(null)
      const [tab, setTab] = useState(TAB_SKILLS)
      const [pathsOpen, setPathsOpen] = useState(false)
      const [stateOpen, setStateOpen] = useState(false)
      /**
       * 文本字段的**未提交草稿**（`field -> 用户刚敲的文本`）。
       *
       * 为什么需要它：输入框的值来自设置镜像，而镜像是**宿主应答回来**才变的。
       * 不留草稿的话，用户每敲一个字符，输入框都会先被 React 按旧值重置一次 ——
       * 那是典型的受控输入丢字符/光标跳位。草稿让"用户看到的"始终是他自己敲的。
       *
       * 为什么改成**失焦/回车才写**：每次写入都会让宿主把 patch 文件原子重写一遍。
       * 逐字符写会为一次编辑产生几十次写盘（以及编辑器的备份文件）。开关与语言是
       * 离散选择，仍然即时写 —— 只有这两个路径框需要"敲完再提交"。
       */
      const [drafts, setDrafts] = useState({})

      // 只读状态：一次挂载读一次。**失败不是错误状态**（这个端点是可选的），
      // 页面照常渲染，只在状态块里说"读不到"。
      useEffect(() => {
        let cancelled = false
        const load = async () => {
          try {
            const res = await fetch(STATUS_URL, { cache: 'no-store' })
            if (!res.ok) throw new Error('HTTP ' + res.status)
            const payload = await res.json()
            if (cancelled) return
            setRuntime(payload)
            setRuntimeError(null)
          } catch (error) {
            if (cancelled) return
            setRuntime(null)
            setRuntimeError(String(error && error.message ? error.message : error))
          }
        }
        load()
        return () => { cancelled = true }
      }, [])

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
       */
      const write = useCallback((field, value, mode) => {
        setNotice({ kind: 'pending' })
        let run
        try {
          run = mode === 'unset' ? props.reset(field) : props.save(field, value)
        } catch (_error) {
          clearDraft(field)
          setNotice({ kind: 'error' })
          return
        }
        Promise.resolve(run).then(
          (accepted) => {
            clearDraft(field)
            setNotice({ kind: accepted === false ? 'rejected' : 'saved' })
          },
          () => {
            clearDraft(field)
            setNotice({ kind: 'error' })
          },
        )
      }, [props, clearDraft])

      if (props?.view === 'summary') return t('summary')

      const status = snapshot?.status
      const ready = status === 'ready'
      const writable = ready && snapshot?.writable !== false
      const disabled = !writable || notice?.kind === 'pending'

      const languageOptions = [
        { value: 'zh', label: '中文' },
        { value: 'en', label: 'English' },
      ]

      const noticeText = notice === null ? null
        : notice.kind === 'pending' ? t('state.pending')
          : notice.kind === 'saved' ? t('state.saved')
            : notice.kind === 'rejected' ? t('state.rejected')
              : t('state.error')
      const noticeStyle = notice !== null && (notice.kind === 'rejected' || notice.kind === 'error')
        ? S.statusError
        : S.status

      /** 状态块的一行。读不到就说读不到 —— 编个 0 是另一个意思。 */
      const statusText = (() => {
        if (runtimeError !== null) return t('status.loadError') + ': ' + runtimeError
        const memory = runtime?.memory
        if (memory === null || typeof memory !== 'object') return t('memory.unknown')
        const parts = []
        if (Number.isInteger(memory.workspaces)) parts.push(t('memory.workspaces') + ' ' + memory.workspaces)
        if (Number.isInteger(memory.inbox)) parts.push(t('memory.inbox') + ' ' + memory.inbox)
        if (Number.isInteger(memory.indexChars)) parts.push(t('memory.indexChars') + ' ' + memory.indexChars)
        return parts.length > 0 ? parts.join(' · ') : t('memory.unknown')
      })()

      const whereText = runtime?.source === 'config' ? t('where.config')
        : runtime?.source === 'file' ? t('where.file')
          : t('where.unknown')
      const wherePath = typeof runtime?.path === 'string' ? runtime.path : ''

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
       */
      const pathField = (field) => {
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
        return h('div', { style: S.row },
          h('div', { style: S.labelBlock },
            h('label', { style: S.label, htmlFor: 'dsh-worklog-' + field }, t(field + '.label')),
            h('div', { style: S.hint }, t('path.hint'))),
          h('div', { style: S.control },
            h(Input, {
              id: 'dsh-worklog-' + field,
              'aria-label': t(field + '.label'),
              value: text,
              placeholder: inheritedText(snapshot, field),
              disabled,
              onChange: (event) => {
                const next = event.target.value
                setDrafts((previous) => ({ ...previous, [field]: next }))
              },
              onBlur: commit,
              onKeyDown: (event) => {
                if (event.key === 'Enter') commit()
              },
            }),
            overridden
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
              : null))
      }

      const skillsPanel = h('div', {
        id: TAB_IDS[TAB_SKILLS].panelId,
        role: 'tabpanel',
        'aria-labelledby': TAB_IDS[TAB_SKILLS].tabId,
        style: S.panel,
      },
      switchRow('guidelinesEnabled'),
      row({
        t,
        labelKey: 'guidelinesLanguage.label',
        hintKey: 'guidelinesLanguage.hint',
        control: h(SegmentedControl, {
          id: 'dsh-worklog-guidelines-language',
          value: effectiveValue(snapshot, 'guidelinesLanguage', 'zh'),
          options: languageOptions,
          label: t('language.control'),
          disabled,
          onChange: (next) => { write('guidelinesLanguage', next, 'set') },
        }),
      }),
      h(DisclosureRow, {
        icon: h('span', { 'aria-hidden': 'true' }),
        title: t('paths.title'),
        open: pathsOpen,
        expandable: true,
        expandOnRowClick: true,
        onToggle: () => { setPathsOpen((open) => !open) },
      },
      h('div', { style: S.pathsBody },
        pathField('skillDir'),
        pathField('guidelinesDir'))))

      const memoryPanel = h('div', {
        id: TAB_IDS[TAB_MEMORY].panelId,
        role: 'tabpanel',
        'aria-labelledby': TAB_IDS[TAB_MEMORY].tabId,
        style: S.panel,
      },
      switchRow('memoryEnabled'),
      switchRow('memoryInjectIndex'),
      switchRow('memoryPersonalSearchable', true),
      h(DisclosureRow, {
        icon: h('span', { 'aria-hidden': 'true' }),
        title: t('memory.title'),
        open: stateOpen,
        expandable: true,
        expandOnRowClick: true,
        onToggle: () => { setStateOpen((open) => !open) },
      },
      h('div', { style: S.pathsBody },
        h('p', { style: S.hint }, statusText),
        /* 这一句是防止误解的关键：不写它，用户会在这一页找上传开关而找不到。 */
        h('p', { style: S.hint }, t('memory.note')))))

      const advancedPanel = h('div', {
        id: TAB_IDS[TAB_ADVANCED].panelId,
        role: 'tabpanel',
        'aria-labelledby': TAB_IDS[TAB_ADVANCED].tabId,
        style: S.panel,
      },
      switchRow('verbose'),
      switchRow('modelInvocable'),
      switchRow('userInvocable', true))

      const panels = {
        [TAB_SKILLS]: skillsPanel,
        [TAB_MEMORY]: memoryPanel,
        [TAB_ADVANCED]: advancedPanel,
      }
      const active = tab === TAB_MEMORY || tab === TAB_ADVANCED ? tab : TAB_SKILLS
      const restartNote = {
        [TAB_SKILLS]: t('restart.skills'),
        [TAB_MEMORY]: t('restart.memory'),
        [TAB_ADVANCED]: t('restart.advanced'),
      }[active]

      const tabItems = [
        { value: TAB_SKILLS, label: t('tabs.skills'), id: TAB_IDS[TAB_SKILLS].tabId, panelId: TAB_IDS[TAB_SKILLS].panelId },
        { value: TAB_MEMORY, label: t('tabs.memory'), id: TAB_IDS[TAB_MEMORY].tabId, panelId: TAB_IDS[TAB_MEMORY].panelId },
        { value: TAB_ADVANCED, label: t('tabs.advanced'), id: TAB_IDS[TAB_ADVANCED].tabId, panelId: TAB_IDS[TAB_ADVANCED].panelId },
      ]

      return h('div', { style: S.root },
        ready ? null : h('p', { style: S.statusError, role: 'alert' }, t('state.unavailable')),

        h(SegmentedTabs, {
          items: tabItems,
          value: active,
          onChange: (next) => { setTab(next) },
          label: t('tabs.label'),
        }),

        panels[active],

        noticeText === null ? null : h('p', { style: noticeStyle, role: 'status' }, noticeText),

        h('p', { style: S.hint }, restartNote),
        h('p', { style: S.footer },
          t('where.label') + '：',
          whereText,
          wherePath === '' ? null : h('code', { style: S.code }, ' — ' + wherePath)),
        h('p', { style: S.footer }, t('spec.note') + t('scope.note')))
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
      const t = locale.bind(SETTINGS_NS)

      // ctx.effect 会立即执行回调，并把回调返回的函数当作卸载清理。
      ctx.effect(
        () => locale.register(SETTINGS_NS, { zh: DICT_ZH, en: DICT_EN }),
        'dsh-worklog: settings dictionaries',
      )

      const forms = ctx.configForms
      const mirror = forms.describe()
      /** 当前挂着的那张卡片：{ns, dispose}；没认领到时为 null。 */
      let mounted = null

      /** 为一个 namespace 挂上卡片，返回撤下它的 disposer。 */
      function mountCard(ns) {
        const form = forms.get(ns)
        return ctx.slots.inject('plugins.item', () => ctx.slots.register({
          name: 'plugins.item',
          id: ITEM_ID,
          order: ITEM_ORDER,
          // 条目名走 locale：语言切换时外壳会重新求值这个 thunk。
          label: () => t('title'),
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
        if (ns === undefined) return
        mounted = { ns, dispose: mountCard(ns) }
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
      }, 'dsh-worklog: plugins page card')
    }

    exports.name = 'dsh-worklog'
    exports.inject = inject
    exports.apply = apply

    /**
     * 词典、状态端点与认领判据也导出，**只为可测**（与 `DICT_ZH`/`DICT_EN` 同理）：
     * `tests/audit-client.mjs` 对账两本词典的键集，`tests/audit-client-runtime.mjs`
     * 直接用对抗性输入打 `claimNamespace`，并断言卡片读的是 `STATUS_URL`。
     */
    exports.DICT_ZH = DICT_ZH
    exports.DICT_EN = DICT_EN
    exports.STATUS_URL = STATUS_URL
    exports.FORM_FIELDS = FORM_FIELDS
    exports.claimNamespace = claimNamespace
    return module.exports
  },
})
