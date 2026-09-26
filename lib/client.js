/**
 * dsh-worklog — 设置页（浏览器半边）。
 *
 * 这是一个**手写的普通 JavaScript 文件**，没有构建步骤：包装格式取自
 * `packages/client/tsdown.client.ts` 的 banner/intro/footer，中间的模块体是
 * 普通代码。用 `React.createElement` 而不是 JSX —— JSX 需要转译，那就等于
 * 引入一个构建步骤。
 *
 * `factory(require)` 的参数 `require` **不是** Node 的 require，而是 DSH 浏览器
 * 模块加载器注入的查找函数。它能解析的**只有**九项（`packages/client/web/src/
 * seed.ts` 是权威清单，原文写明是 "the ONLY entities the shell shares into the
 * frozen module table"）：
 *
 *   react / react/jsx-runtime / react-dom / react-dom/client
 *   @deepseek-ai/cordis / @deepseek-ai/dsh-client-store
 *   @deepseek-ai/dsh-client-ui-slots / @deepseek-ai/dsh-client-ui-primitives
 *   @deepseek-ai/dsh-client-ui-dockkit
 *
 * 本文件只用到其中两项（`react`、`@deepseek-ai/dsh-client-ui-primitives`）。
 * 其余服务（locale、slots）一律从 `ctx` 取，不能 require。
 *
 * 读写设置走节点半边起的 HTTP 端点：浏览器半边碰不到文件系统，而 DSH 的
 * `Config`/设置作用域对树外插件不可用（`@deepseek-ai/schemastery` 只存在于
 * 应用的 app.asar 里）。
 *
 * 表单控件不自己写：`ui-primitives` 提供 `Switch` / `SegmentedControl` /
 * `Input` / `DisclosureRow` / `SegmentedTabs`，它们只通过 `--dsw-*` token 取样式，
 * 且不依赖 Cordis。
 *
 * **这一页只管插件自己的装载参数。** 项目级的 `container` / `lessons` / `mode`
 * 曾经也在这里（标着「插件不读」），现在撤掉了 —— 它们描述的是某个项目自己的
 * `<容器>/.config.json`，而那个文件由 `journal.py config` 改。两个设置面不许管
 * 同一件事，是这套设计里唯一不许破的规则（见 `docs/settings-spec.md` §零）。
 * 节点半边仍然存着这三个键、也仍然在路由里报它们（`projectDefaults`），那是为了
 * 让消费者不能把它们误当成插件设置 —— 只是这一页不再提供控件。
 */
window.__ModuleLoader__.load({
  id: 'dsh-worklog',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports

    /** 设置面板需要 React（与内置设置页共用同一份实例）。 */
    const React = require('react')
    /** 现成的基础控件，避免自己写开关/分段控件，也避免自带 CSS。 */
    const primitives = require('@deepseek-ai/dsh-client-ui-primitives')
    const { Switch, Input, SegmentedControl, DisclosureRow, SegmentedTabs } = primitives

    const h = React.createElement
    const { useCallback, useEffect, useRef, useState } = React

    /** 节点半边注册的唯一点。改这里必须同时改 `lib/index.js` 的 SETTINGS_ROUTE_PATH。 */
    const SETTINGS_URL = '/plugins/dsh-worklog/settings.json'
    /** locale 命名空间：只属于这个设置页。 */
    const SETTINGS_NS = 'dsh-worklog.settings'

    /**
     * 两个分页。
     *
     * `SegmentedTabs` **只渲染标签栏，面板由调用方持有**，所以 tab 与 panel 的
     * 关联要自己连：它用 `items[].id` 当标签页的 DOM id、`items[].panelId` 当
     * `aria-controls`，面板那边反过来用 `aria-labelledby` 指回标签页的 id。这一对
     * 字符串必须成对出现，写错了不会报错，只会让无障碍树里出现悬空引用。
     */
    const TAB_SKILLS = 'skills'
    const TAB_OTHERS = 'others'
    const TAB_IDS = {
      [TAB_SKILLS]: { tabId: 'dsh-worklog-tab-skills', panelId: 'dsh-worklog-panel-skills' },
      [TAB_OTHERS]: { tabId: 'dsh-worklog-tab-others', panelId: 'dsh-worklog-panel-others' },
    }

    /**
     * 文案词典。中英两份都在 —— 不是"先只做中文"的将就：文案量很小，
     * 一次补齐比留一个"英文界面里突然冒出中文"的状态好。
     *
     * 语言名（中文/English）在两种语言下都写成它自己的语言，这是语言选择器的惯例。
     */
    const DICT_ZH = {
      'nav.label': '工作记录',
      'title': '工作记录',
      'intro': '这个插件向会话目录登记两个技能：项目工作记录，以及可选的可靠性准则。'
        + '下面的选项在插件装载时读取，改完需要重启 DSH 才生效。',
      'tabs.label': '设置分组',
      'tabs.skills': '技能',
      'tabs.others': '其他',
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
      'verbose.label': '装载时打日志',
      'verbose.hint': '装载时多打一行日志：技能名与它实际读的文件。',
      'modelInvocable.label': '允许模型自动调用',
      'modelInvocable.hint': '关闭后模型不会自己调用这两个技能，你仍可以手动调用。',
      'userInvocable.label': '允许手动调用',
      'userInvocable.hint': '关闭后这两个技能不再出现在可手动调用的清单里。',
      'effective': '生效值',
      'defaultSuffix': '（默认）',
      'state.loading': '正在读取…',
      'state.loadError': '读取设置失败',
      'state.pending': '正在保存…',
      'state.saved': '已保存，重启 DSH 后生效',
      'state.error': '保存失败',
      'restart': '技能目录与开关是装载参数：改完需重启 DSH 才生效。',
      'file.label': '设置文件',
      'file.missing': '（文件还不存在，第一次保存时创建）',
      'file.broken': '（文件读不出来，当前用的是内置默认值）',
      'spec.note': '兼容性说明：',
      'scope.note': '容器目录名、经验目录名与默认精细度是项目级设置，不在这一页 —— '
        + '它们属于项目自己的 `.config.json`，用 `journal.py config` 改；'
        + '改名类字段对已有项目是破坏性的。',
    }

    /** 英文词典。键集必须与中文完全一致。 */
    const DICT_EN = {
      'nav.label': 'Worklog',
      'title': 'Worklog',
      'intro': 'This plugin registers two skills into the session catalog: project work-log, '
        + 'and the optional reliability guidelines. The options below are read when the plugin '
        + 'mounts, so changing them needs a DSH restart.',
      'tabs.label': 'Settings groups',
      'tabs.skills': 'Skills',
      'tabs.others': 'Other',
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
      'path.hint': 'A relative path resolves from the package root; leave it blank for the bundled default.',
      'verbose.label': 'Log at mount',
      'verbose.hint': 'Logs one extra line when the plugin mounts: the skill name and the file '
        + 'it actually reads.',
      'modelInvocable.label': 'Let the model call these skills',
      'modelInvocable.hint': 'Off: the model will not call them on its own; you can still call '
        + 'them yourself.',
      'userInvocable.label': 'Let you call these skills',
      'userInvocable.hint': 'Off: they no longer appear in the list of skills you can invoke '
        + 'yourself.',
      'effective': 'In effect',
      'defaultSuffix': ' (default)',
      'state.loading': 'Loading…',
      'state.loadError': 'Could not load the settings',
      'state.pending': 'Saving…',
      'state.saved': 'Saved — takes effect after a DSH restart',
      'state.error': 'Save failed',
      'restart': 'The skill directories and switches are load-time options: a DSH restart is required.',
      'file.label': 'Settings file',
      'file.missing': '(not created yet — the first save creates it)',
      'file.broken': '(unreadable — the built-in defaults are in use)',
      'spec.note': 'Compatibility note: ',
      'scope.note': 'The container directory name, the lessons directory name and the default '
        + 'granularity are project-level settings and are not offered here — they belong to a '
        + 'project\'s own `.config.json`, changed with `journal.py config`. Rename-style fields '
        + 'are destructive to a project that already has records.',
    }

    /* ---------------------------------------------------------------- 样式 --
     * 只用 `--dsw-*` token 和行内样式，不自带 CSS 文件。设置页里那十几个控件
     * 的间距不值得为它引入一份样式表 —— `dsh-status-rotator` 那 259 KB 有一大
     * 半就是自带的 CSS。 */
    const S = {
      root: { display: 'flex', flexDirection: 'column', gap: '12px', maxWidth: '760px', color: 'var(--dsw-alias-label-primary)' },
      title: { margin: 0, fontSize: '18px', fontWeight: 600 },
      intro: { margin: 0, fontSize: '13px', lineHeight: 1.5, color: 'var(--dsw-alias-label-tertiary)' },
      /* 字段行 = 官方设置页的 chrome：标签在左、控件在右、分隔线在**行下**。
         官方实现见 ui-settings-general/DeveloperToolsRow.module.css:
             display:flex; align-items:center; justify-content:space-between;
             gap:24px; padding:16px 0;
             border-bottom:.5px solid var(--dsw-alias-border-l2)
         最后一行不画线（GeneralSection 的做法）。留空 `borderBottom` 交给调用方。 */
      row: {
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: '24px', padding: '16px 0',
        borderBottom: '0.5px solid var(--dsw-alias-border-l2)',
      },
      rowLast: { borderBottom: 'none' },
      /* 左侧文案块：标签 + 说明，说明紧跟标签下方。 */
      labelBlock: { display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0 },
      /* 行右侧：可选"生效值"标记 + 控件，竖向贴右。 */
      control: { display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '4px' },
      label: { fontSize: '14px', lineHeight: '20px' },
      hint: { margin: 0, fontSize: '12px', lineHeight: '18px', color: 'var(--dsw-alias-label-secondary)' },
      // 行右侧的"当前生效值"，比说明更弱一档。
      effective: { fontSize: '12px', color: 'var(--dsw-alias-label-tertiary)' },
      input: { width: '320px' },
      status: { fontSize: '12px', color: 'var(--dsw-alias-label-secondary)' },
      statusError: { fontSize: '12px', color: 'var(--dsw-alias-label-error)' },
      footer: { fontSize: '12px', color: 'var(--dsw-alias-label-tertiary)' },
      code: { wordBreak: 'break-all', fontFamily: 'var(--dsw-font-family)', opacity: 0.85 },
      /* 面板：只包住被选中的那一组字段，`SegmentedTabs` 自己不渲染面板。 */
      panel: { display: 'flex', flexDirection: 'column' },
      /* 折叠区展开后的内容。 */
      pathsBody: { display: 'flex', flexDirection: 'column' },
    }

    /**
     * 行左侧的标签块：标签 + 可选说明。
     *
     * 右侧那栏「生效值（默认）」**不放在这里**，而是调用方作为行的兄弟节点渲染。
     * 原因是实测得来：`tests/audit-client-runtime.mjs` 的测试运行时只展开顶层
     * 组件，不下钻函数组件，所以任何藏在 `Text` 内部的文本对断言都是不可见的 ——
     * 那条断言语义上在测"只有两个装载参数带标记"，实际却读不到标记，一度靠
     * 开发者磁盘上的设置文件"恰好"通过。宿主元素直接放在树里才可断言。
     */
    function Text({ t, labelKey, hintKey }) {
      return h('div', { style: S.labelBlock },
        h('span', { style: S.label }, t(labelKey)),
        hintKey === undefined ? null : h('p', { style: S.hint }, t(hintKey)))
    }

    /** 行右侧的"当前生效值（默认）"标记：宿主元素，可被测试与遍历看到。 */
    function Mark({ text }) {
      return text === null || text === undefined || text === ''
        ? null
        : h('span', { style: S.effective }, text)
    }

    /** 文本输入行：标签在左，输入框在右，分隔线在行下。 */
    function textRow({ t, labelKey, value, effectiveText, hintKey, onChange, placeholder, last }) {
      const mark = effectiveText === null || effectiveText === undefined || effectiveText === ''
        ? ''
        : effectiveText
      return h('div', {
        key: labelKey,
        // 标记的"有/无"写在宿主属性上而不是只写进文本：`audit-client-runtime.mjs`
        // 的运行时只展开顶层组件，藏进 `Text` 子树的字符串对断言不可见。
        'data-mark': mark === '' ? 'none' : mark,
        style: last === true ? { ...S.row, ...S.rowLast } : S.row,
      },
      h(Text, { t, labelKey, hintKey }),
      h('div', { style: S.control },
        h(Mark, { text: mark }),
        h(Input, {
          value,
          style: S.input,
          spellCheck: false,
          'aria-label': t(labelKey),
          placeholder: placeholder === undefined ? '' : placeholder,
          onChange: (event) => { onChange(event.target.value) },
        })))
    }

    /** 开关行：chrome 与 `textRow` 相同，右边换成一个 `Switch`。 */
    function switchRow({ t, labelKey, hintKey, checked, disabled, onChange, last }) {
      return h('div', {
        key: labelKey,
        style: last === true ? { ...S.row, ...S.rowLast } : S.row,
      },
      h(Text, { t, labelKey, hintKey }),
      h(Switch, {
        checked,
        // `Switch` 的设计要求必填 label：不允许交出没有无障碍名的开关。
        label: t(labelKey),
        disabled,
        onChange,
      }))
    }

    /**
     * 设置面板。
     *
     * `props.t` 是框架注入的翻译函数（注册时声明了 `locale:`，ui-slots 的渲染
     * 机制就会把 `t` 放进 props）。仍留一个兜底：拿不到时用中文词典，设置页
     * 退化成中文，而不是整页崩掉。
     */
    function SettingsPanel(props) {
      const fallbackT = useCallback((key) => {
        const dict = DICT_ZH
        return dict[key] === undefined ? key : dict[key]
      }, [])
      const t = typeof props?.t === 'function' ? props.t : fallbackT

      /**
       * 表单值：**只有插件装载时读的那些键**。
       *
       * 项目级的 `container` / `lessons` / `mode` 刻意不在这里。它们在磁盘上、
       * 由节点半边保留并回报（`projectDefaults`），但这一页既不显示也不提交它们；
       * 路由把请求体当补丁，所以省掉这三个键 = 保留原值，不会丢。
       */
      const [form, setForm] = useState({
        guidelinesEnabled: true,
        guidelinesLanguage: 'zh',
        skillDir: '',
        guidelinesDir: '',
        verbose: false,
        modelInvocable: true,
        userInvocable: true,
      })
      /** 节点半边回报的生效值（含默认值），用来显示"留空 = 默认"。 */
      const [effective, setEffective] = useState(null)
      const [filePath, setFilePath] = useState('')
      const [fileError, setFileError] = useState(null)
      const [phase, setPhase] = useState('loading')
      const [errorText, setErrorText] = useState('')
      const [pathsOpen, setPathsOpen] = useState(false)
      /** 当前分页。默认「技能」—— 那一组是装载行为的主开关。 */
      const [tab, setTab] = useState(TAB_SKILLS)
      /** 保存队列的尾。串行化，避免连点两下开关时两个请求交错。 */
      const queue = useRef(Promise.resolve())

      const applyResponse = useCallback((payload) => {
        const stored = payload?.settings && typeof payload.settings === 'object' ? payload.settings : {}
        setForm((prev) => ({
          ...prev,
          // 磁盘上没有的键就保留默认显示值；空串是"用默认"，照实显示。
          guidelinesEnabled: typeof stored.guidelinesEnabled === 'boolean'
            ? stored.guidelinesEnabled : true,
          guidelinesLanguage: stored.guidelinesLanguage === 'en' ? 'en' : 'zh',
          skillDir: typeof stored.skillDir === 'string' ? stored.skillDir : '',
          guidelinesDir: typeof stored.guidelinesDir === 'string' ? stored.guidelinesDir : '',
          verbose: typeof stored.verbose === 'boolean' ? stored.verbose : false,
          modelInvocable: typeof stored.modelInvocable === 'boolean' ? stored.modelInvocable : true,
          userInvocable: typeof stored.userInvocable === 'boolean' ? stored.userInvocable : true,
        }))
        setEffective(payload?.effective ?? null)
        setFilePath(typeof payload?.path === 'string' ? payload.path : '')
        setFileError(typeof payload?.error === 'string' ? payload.error : null)
        // `payload.projectDefaults` 被刻意忽略：这一页不展示也不改它，见上面的 `form`。
      }, [])

      useEffect(() => {
        let cancelled = false
        const load = async () => {
          try {
            const res = await fetch(SETTINGS_URL, { cache: 'no-store' })
            if (!res.ok) throw new Error('HTTP ' + res.status)
            const payload = await res.json()
            if (cancelled) return
            applyResponse(payload)
            setPhase('ready')
          } catch (error) {
            if (cancelled) return
            setErrorText(String(error && error.message ? error.message : error))
            setPhase('load-error')
          }
        }
        load()
        return () => { cancelled = true }
      }, [applyResponse])

      /** 把一份完整表单发给节点半边，按队列串行。 */
      const submit = useCallback((state) => {
        const run = async () => {
          setPhase('pending')
          try {
            const res = await fetch(SETTINGS_URL, {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify(state),
            })
            const text = await res.text()
            let payload = null
            try {
              payload = JSON.parse(text)
            } catch {
              /* 非 JSON 响应：用 HTTP 状态判定，下面统一处理 */
            }
            if (!res.ok) {
              throw new Error(payload && payload.error ? payload.error : 'HTTP ' + res.status)
            }
            applyResponse(payload)
            setErrorText('')
            setPhase('saved')
          } catch (error) {
            setErrorText(String(error && error.message ? error.message : error))
            setPhase('save-error')
          }
        }
        queue.current = queue.current.then(run, run)
        return queue.current
      }, [applyResponse])

      /**
       * 改一个字段并保存整份表单。
       *
       * 用函数式 setState 是有意的：值取自上一份提交时的 state，所以连点两下
       * 开关、或在输入框里连打几个字都不会互相覆盖。
       */
      const change = useCallback((key, value) => {
        setForm((prev) => {
          if (prev[key] === value) return prev
          const next = { ...prev, [key]: value }
          submit(next)
          return next
        })
      }, [submit])

      if (phase === 'loading') {
        return h('div', { style: S.root }, h('p', { style: S.hint }, t('state.loading')))
      }
      if (phase === 'load-error') {
        return h('div', { style: S.root },
          h('p', { role: 'alert', style: S.statusError }, t('state.loadError') + ': ' + errorText))
      }

      /** "留空 = 包内默认" 的显示文本。 */
      const asDefault = (value, fallback) => (value === '' || value === undefined
        ? String(fallback) + t('defaultSuffix')
        : '')

      const languageOptions = [
        { value: 'zh', label: '中文' },
        { value: 'en', label: 'English' },
      ]

      const pending = phase === 'pending'

      /** 标签栏的数据。label 是本地化的，accessibility 名走 `tabs.label`。 */
      const tabItems = [
        { value: TAB_SKILLS, label: t('tabs.skills'), id: TAB_IDS[TAB_SKILLS].tabId, panelId: TAB_IDS[TAB_SKILLS].panelId },
        { value: TAB_OTHERS, label: t('tabs.others'), id: TAB_IDS[TAB_OTHERS].tabId, panelId: TAB_IDS[TAB_OTHERS].panelId },
      ]
      /** 只渲染被选中的那一个面板（value 不在表里时退回第一个）。 */
      const active = tab === TAB_OTHERS ? TAB_OTHERS : TAB_SKILLS

      const status = phase === 'pending'
        ? h('span', { style: S.status }, t('state.pending'))
        : phase === 'saved'
          ? h('span', { style: S.status, role: 'status' }, t('state.saved'))
          : phase === 'save-error'
            ? h('span', { style: S.statusError, role: 'alert' }, t('state.error') + ': ' + errorText)
            : null

      /* ── 面板「技能」：准则的开关与语言，路径收在折叠区里 ──────────────── */
      const skillsPanel = h('div', {
        id: TAB_IDS[TAB_SKILLS].panelId,
        role: 'tabpanel',
        'aria-labelledby': TAB_IDS[TAB_SKILLS].tabId,
        style: S.panel,
      },
      switchRow({
        t,
        labelKey: 'guidelinesEnabled.label',
        hintKey: 'guidelinesEnabled.hint',
        checked: form.guidelinesEnabled,
        disabled: pending,
        onChange: (next) => { change('guidelinesEnabled', next) },
      }),

      h('div', { style: { ...S.row, ...S.rowLast } },
        h(Text, { t, labelKey: 'guidelinesLanguage.label', hintKey: 'guidelinesLanguage.hint' }),
        h(SegmentedControl, {
          id: 'dsh-worklog-guidelines-language',
          value: form.guidelinesLanguage,
          options: languageOptions,
          label: t('language.control'),
          disabled: pending,
          onChange: (next) => { change('guidelinesLanguage', next) },
        })),

      /* 路径折叠区。两个目录是**装载参数**（不是项目级设置），只是不常改，所以
         默认收起；`DisclosureRow` 只在 `open` 时渲染 children，收起时这两行真的
         不在 DOM 里。 */
      h(DisclosureRow, {
        icon: h('span', { 'aria-hidden': 'true' }),
        title: t('paths.title'),
        open: pathsOpen,
        expandable: true,
        expandOnRowClick: true,
        onToggle: () => { setPathsOpen((open) => !open) },
      },
      h('div', { style: S.pathsBody },
        textRow({
          t,
          labelKey: 'skillDir.label',
          value: form.skillDir,
          effectiveText: asDefault(form.skillDir, effective?.skillDir),
          hintKey: 'path.hint',
          placeholder: effective?.skillDir ?? '',
          onChange: (value) => { change('skillDir', value) },
        }),
        textRow({
          t,
          labelKey: 'guidelinesDir.label',
          value: form.guidelinesDir,
          effectiveText: asDefault(form.guidelinesDir, effective?.guidelinesDir),
          hintKey: 'path.hint',
          last: true,
          placeholder: effective?.guidelinesDir ?? '',
          onChange: (value) => { change('guidelinesDir', value) },
        }))))

      /* ── 面板「其他」：三个装载开关。它们早就被 `effectiveSettings()` 读，
             但一直没有控件，所以这一页此前根本设不了它们。 ──────────────── */
      const othersPanel = h('div', {
        id: TAB_IDS[TAB_OTHERS].panelId,
        role: 'tabpanel',
        'aria-labelledby': TAB_IDS[TAB_OTHERS].tabId,
        style: S.panel,
      },
      switchRow({
        t,
        labelKey: 'verbose.label',
        hintKey: 'verbose.hint',
        checked: form.verbose,
        disabled: pending,
        onChange: (next) => { change('verbose', next) },
      }),
      switchRow({
        t,
        labelKey: 'modelInvocable.label',
        hintKey: 'modelInvocable.hint',
        checked: form.modelInvocable,
        disabled: pending,
        onChange: (next) => { change('modelInvocable', next) },
      }),
      switchRow({
        t,
        labelKey: 'userInvocable.label',
        hintKey: 'userInvocable.hint',
        checked: form.userInvocable,
        disabled: pending,
        last: true,
        onChange: (next) => { change('userInvocable', next) },
      }))

      return h('div', { style: S.root },
        h('h2', { style: S.title }, t('title')),
        h('p', { style: S.intro }, t('intro')),

        /* ── 标签栏：只渲染标签，面板是下面那两个之一 ────────────────────── */
        h(SegmentedTabs, {
          items: tabItems,
          value: active,
          onChange: (next) => { setTab(next) },
          label: t('tabs.label'),
        }),

        active === TAB_SKILLS ? skillsPanel : othersPanel,

        status,

        h('p', { style: S.hint }, t('restart')),
        h('p', { style: S.footer },
          t('file.label') + '：',
          filePath === '' ? t('state.loading') : h('code', { style: S.code }, filePath),
          fileError !== null ? ' ' + t('file.broken') : null),
        h('p', { style: S.footer }, t('spec.note') + t('scope.note')))
    }

    /**
     * 客户端插件的装载。
     *
     * `inject: ['locale', 'slots']`：两个都是设置页的硬需求 —— 没有 slots 就
     * 没有挂载点，没有 locale 就拿不到 `t`（框架仅在注册声明了 `locale:` 时
     * 注入 `t`，而它由 locale 插件安装）。这两个服务在正常组合里都是 immediately
     * 层，早于本插件。
     */
    const inject = ['locale', 'slots']

    function apply(ctx) {
      const locale = ctx.locale
      const t = locale.bind(SETTINGS_NS)

      // ctx.effect 会立即执行回调，并把回调返回的函数当作卸载清理。
      // locale.register 返回的正是 disposer，直接交出去。
      ctx.effect(
        () => locale.register(SETTINGS_NS, { zh: DICT_ZH, en: DICT_EN }),
        'dsh-worklog: settings dictionaries',
      )

      ctx.slots.inject('settings.section', () => ctx.slots.register({
        name: 'settings.section',
        id: 'dsh-worklog',
        order: 50,
        // 导航名走 locale：标签是 thunk，语言切换时外壳重新求值。
        label: () => t('nav.label'),
        locale: SETTINGS_NS,
      }, SettingsPanel))
    }

    exports.name = 'dsh-worklog'
    exports.inject = inject
    exports.apply = apply
    return module.exports
  },
})
