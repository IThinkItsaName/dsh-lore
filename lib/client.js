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
 * `Input` / `DisclosureRow`，它们只通过 `--dsw-*` token 取样式，且不依赖 Cordis。
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
    const { Switch, Input, SegmentedControl, DisclosureRow } = primitives

    const h = React.createElement
    const { useCallback, useEffect, useRef, useState } = React

    /** 节点半边注册的唯一点。改这里必须同时改 `lib/index.js` 的 SETTINGS_ROUTE_PATH。 */
    const SETTINGS_URL = '/plugins/dsh-worklog/settings.json'
    /** locale 命名空间：只属于这个设置页。 */
    const SETTINGS_NS = 'dsh-worklog.settings'

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
      'guidelinesEnabled.label': '启用可靠性准则技能',
      'guidelinesEnabled.hint': '关闭后 `reliability-guidelines` 技能不再登记，'
        + '`project-work-log` 不受影响。',
      'guidelinesLanguage.label': '准则语言',
      'guidelinesLanguage.hint': '只影响准则那一份技能；`project-work-log` 本身固定是中文。',
      'language.control': '准则语言',
      'mode.label': '新项目默认精细度',
      'mode.control': '新项目默认精细度',
      'mode.full': '完整',
      'mode.session': '会话',
      'mode.digest': '摘要',
      'mode.milestone': '里程碑',
      'mode.hint': '新项目的精细度默认档，也就是 `.config.json` 里的 `mode`；'
        + '已在跑的项目以自己那份为准。',
      'advanced.title': '高级',
      'skillDir.label': '工作记录技能目录',
      'guidelinesDir.label': '准则技能目录',
      'container.label': '容器目录名',
      'lessons.label': '经验目录名',
      'destructive': '破坏性',
      'path.hint': '相对路径从包根目录算起；留空则用包内默认值。',
      'projectDefaults.label': '新项目默认值',
      'projectDefaults.notApplied': '（插件不读）',
      'projectDefaults.hint': '新建项目的初始值：写进该项目自己的 `.config.json`，'
        + '由 `journal.py` 读取。',
      'container.hint': '新项目的容器目录名（默认 `work_log`）。已有项目改了名，'
        + '`journal.py` 找不到记录，而且不会提示"是不是改名了"。',
      'lessons.hint': '新项目的经验目录名（默认 `lessons`）。实际存在的目录优先于这个默认值。',
      'effective': '生效值',
      'defaultSuffix': '（默认）',
      'state.loading': '正在读取…',
      'state.loadError': '读取设置失败',
      'state.pending': '正在保存…',
      'state.saved': '已保存，重启 DSH 后生效',
      'state.error': '保存失败',
      'restart': '技能目录与开关是装载参数，改完需重启 DSH；新项目默认值不在其中，'
        + '它们只影响之后新建的项目。',
      'file.label': '设置文件',
      'file.missing': '（文件还不存在，第一次保存时创建）',
      'file.broken': '（文件读不出来，当前用的是内置默认值）',
      'spec.note': '兼容性说明：',
    }

    /** 英文词典。键集必须与中文完全一致。 */
    const DICT_EN = {
      'nav.label': 'Worklog',
      'title': 'Worklog',
      'intro': 'This plugin registers two skills into the session catalog: project work-log, '
        + 'and the optional reliability guidelines. The options below are read when the plugin '
        + 'mounts, so changing them needs a DSH restart.',
      'guidelinesEnabled.label': 'Enable the reliability-guidelines skill',
      'guidelinesEnabled.hint': 'Switching this off stops registering `reliability-guidelines`; '
        + '`project-work-log` is unaffected.',
      'guidelinesLanguage.label': 'Guidelines language',
      'guidelinesLanguage.hint': 'Affects the guidelines skill only — `project-work-log` itself '
        + 'is written in Chinese.',
      'language.control': 'Guidelines language',
      'mode.label': 'Default granularity for new projects',
      'mode.control': 'Default granularity for new projects',
      'mode.full': 'Full',
      'mode.session': 'Session',
      'mode.digest': 'Digest',
      'mode.milestone': 'Milestone',
      'mode.hint': 'The granularity default for a NEW project — the `mode` in its `.config.json`; '
        + 'projects already running go by their own.',
      'advanced.title': 'Advanced',
      'skillDir.label': 'Work-log skill directory',
      'guidelinesDir.label': 'Guidelines skill directory',
      'container.label': 'Container directory name',
      'lessons.label': 'Lessons directory name',
      'destructive': 'Destructive',
      'path.hint': 'A relative path resolves from the package root; leave it blank for the bundled default.',
      'projectDefaults.label': 'New-project defaults',
      'projectDefaults.notApplied': ' (not read by the plugin)',
      'projectDefaults.hint': 'Initial values for a NEW project: they go into that project\'s '
        + '`.config.json`, which `journal.py` reads.',
      'container.hint': 'The container directory name for a NEW project (`work_log` by default). '
        + 'Renaming an existing project makes `journal.py` miss its records, and it will not '
        + 'suggest that a rename happened.',
      'lessons.hint': 'The lessons directory name for a NEW project (`lessons` by default). '
        + 'A directory that actually exists wins over this default.',
      'effective': 'In effect',
      'defaultSuffix': ' (default)',
      'state.loading': 'Loading…',
      'state.loadError': 'Could not load the settings',
      'state.pending': 'Saving…',
      'state.saved': 'Saved — takes effect after a DSH restart',
      'state.error': 'Save failed',
      'restart': 'The skill directories and switches are load-time options: a DSH restart is '
        + 'required. The new-project defaults are not — they only affect projects created afterwards.',
      'file.label': 'Settings file',
      'file.missing': '(not created yet — the first save creates it)',
      'file.broken': '(unreadable — the built-in defaults are in use)',
      'spec.note': 'Compatibility note: ',
    }

    /* ---------------------------------------------------------------- 样式 --
     * 只用 `--dsw-*` token 和行内样式，不自带 CSS 文件。设置页里那十几个控件
     * 的间距不值得为它引入一份样式表 —— `dsh-status-rotator` 那 259 KB 有一大
     * 半就是自带的 CSS。 */
    const S = {
      root: { display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '720px' },
      title: { margin: 0, fontSize: '16px', fontWeight: 600 },
      intro: { margin: 0, fontSize: '13px', lineHeight: 1.6, color: 'var(--dsw-text-secondary, #8a8a8a)' },
      field: { display: 'flex', flexDirection: 'column', gap: '6px' },
      fieldHead: { display: 'flex', alignItems: 'center', gap: '8px' },
      label: { fontSize: '13px', fontWeight: 500 },
      hint: { margin: 0, fontSize: '12px', lineHeight: 1.6, color: 'var(--dsw-text-secondary, #8a8a8a)' },
      switchRow: { display: 'flex', alignItems: 'center', gap: '10px' },
      effective: { fontSize: '12px', color: 'var(--dsw-text-secondary, #8a8a8a)' },
      input: { width: '100%' },
      tag: {
        fontSize: '11px', padding: '1px 6px', borderRadius: '4px',
        border: '1px solid var(--dsw-border, #d0d0d0)',
        color: 'var(--dsw-text-secondary, #8a8a8a)',
      },
      status: { fontSize: '12px' },
      statusError: { fontSize: '12px', color: 'var(--dsw-danger, #d03050)' },
      footer: { fontSize: '12px', color: 'var(--dsw-text-secondary, #8a8a8a)' },
      code: { wordBreak: 'break-all', fontFamily: 'var(--dsw-font-mono, monospace)' },
      advancedBody: { display: 'flex', flexDirection: 'column', gap: '14px', paddingTop: '12px' },
    }

    /** 一行的标题 + 右侧"当前生效值"。 */
    function head(t, labelKey, effectiveText) {
      return h('div', { style: S.fieldHead },
        h('span', { style: S.label }, t(labelKey)),
        effectiveText === null ? null : h('span', { style: S.effective }, effectiveText))
    }

    /** 文本输入行：label + 输入框 + 说明。 */
    function textRow({ t, labelKey, value, effectiveText, hintKey, destructive, onChange, placeholder }) {
      return h('div', { key: labelKey, style: S.field },
        h('div', { style: S.fieldHead },
          h('span', { style: S.label }, t(labelKey)),
          destructive === true ? h('span', { style: S.tag }, t('destructive')) : null,
          effectiveText === null ? null : h('span', { style: S.effective }, effectiveText)),
        h(Input, {
          value,
          style: S.input,
          spellCheck: false,
          'aria-label': t(labelKey),
          placeholder: placeholder === undefined ? '' : placeholder,
          onChange: (event) => { onChange(event.target.value) },
        }),
        h('p', { style: S.hint }, t(hintKey)))
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

      /** 表单值。只有已知键，未知键由节点半边保留，这里不展示也不丢。 */
      const [form, setForm] = useState({
        guidelinesEnabled: true,
        guidelinesLanguage: 'zh',
        skillDir: '',
        guidelinesDir: '',
        container: '',
        lessons: '',
        mode: 'full',
      })
      /** 节点半边回报的生效值（含默认值），用来显示"留空 = 默认"。 */
      const [effective, setEffective] = useState(null)
      /** 节点半边回报的项目默认值：插件只存不读，见下面的"新项目默认值"一组。 */
      const [projectDefaults, setProjectDefaults] = useState(null)
      const [filePath, setFilePath] = useState('')
      const [fileError, setFileError] = useState(null)
      const [phase, setPhase] = useState('loading')
      const [errorText, setErrorText] = useState('')
      const [advancedOpen, setAdvancedOpen] = useState(false)
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
          container: typeof stored.container === 'string' ? stored.container : '',
          lessons: typeof stored.lessons === 'string' ? stored.lessons : '',
          mode: typeof stored.mode === 'string' ? stored.mode : 'full',
        }))
        setEffective(payload?.effective ?? null)
        setProjectDefaults(payload?.projectDefaults ?? null)
        setFilePath(typeof payload?.path === 'string' ? payload.path : '')
        setFileError(typeof payload?.error === 'string' ? payload.error : null)
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

      /** 项目默认值里的一项；节点半边没报这项时是空串（占位符就空着，不编一个）。 */
      const projectValue = (key) => (typeof projectDefaults?.values?.[key] === 'string'
        ? projectDefaults.values[key]
        : '')

      /**
       * 这一组是"插件不读"的 —— 除非节点半边明确说它读了。
       *
       * 默认按"不读"渲染：标记缺失时（旧版节点半边、缓存住的旧 bundle）宁可多写一句
       * 说明，也不能让页面看起来像插件会用它。判据由节点半边给出，不在这里另立一份。
       */
      const projectNotApplied = projectDefaults?.appliedByPlugin !== true

      const languageOptions = [
        { value: 'zh', label: '中文' },
        { value: 'en', label: 'English' },
      ]
      const modeOptions = [
        { value: 'full', label: t('mode.full') },
        { value: 'session', label: t('mode.session') },
        { value: 'digest', label: t('mode.digest') },
        { value: 'milestone', label: t('mode.milestone') },
      ]

      const status = phase === 'pending'
        ? h('span', { style: S.status }, t('state.pending'))
        : phase === 'saved'
          ? h('span', { style: S.status, role: 'status' }, t('state.saved'))
          : phase === 'save-error'
            ? h('span', { style: S.statusError, role: 'alert' }, t('state.error') + ': ' + errorText)
            : null

      return h('div', { style: S.root },
        h('h2', { style: S.title }, t('title')),
        h('p', { style: S.intro }, t('intro')),

        /* ── 主区：两个字段 ───────────────────────────────────────────── */
        h('div', { style: S.field },
          h('div', { style: S.switchRow },
            h(Switch, {
              checked: form.guidelinesEnabled,
              label: t('guidelinesEnabled.label'),
              disabled: phase === 'pending',
              onChange: (next) => { change('guidelinesEnabled', next) },
            }),
            h('span', { style: S.label }, t('guidelinesEnabled.label'))),
          h('p', { style: S.hint }, t('guidelinesEnabled.hint'))),

        h('div', { style: S.field },
          head(t, 'guidelinesLanguage.label', null),
          h(SegmentedControl, {
            id: 'dsh-worklog-guidelines-language',
            value: form.guidelinesLanguage,
            options: languageOptions,
            label: t('language.control'),
            disabled: phase === 'pending',
            onChange: (next) => { change('guidelinesLanguage', next) },
          }),
          h('p', { style: S.hint }, t('guidelinesLanguage.hint'))),

        status,

        /* ── 高级折叠区 ──────────────────────────────────────────────── */
        h(DisclosureRow, {
          icon: h('span', { 'aria-hidden': 'true' }),
          title: t('advanced.title'),
          open: advancedOpen,
          expandable: true,
          expandOnRowClick: true,
          onToggle: () => { setAdvancedOpen((open) => !open) },
        },
        h('div', { style: S.advancedBody },
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
            placeholder: effective?.guidelinesDir ?? '',
            onChange: (value) => { change('guidelinesDir', value) },
          }),
          /* ── 新项目默认值：插件只存不读，写进项目自己的 .config.json ───── */
          h('div', { key: 'projectDefaults.head', style: S.field },
            h('span', { style: S.label },
              t('projectDefaults.label'),
              projectNotApplied ? t('projectDefaults.notApplied') : null),
            h('p', { style: S.hint }, t('projectDefaults.hint'))),
          textRow({
            t,
            labelKey: 'container.label',
            value: form.container,
            // 没有"生效值"可显示：这三项不参与插件解析，右侧那栏只属于装载参数。
            effectiveText: null,
            hintKey: 'container.hint',
            destructive: true,
            placeholder: projectValue('container'),
            onChange: (value) => { change('container', value) },
          }),
          textRow({
            t,
            labelKey: 'lessons.label',
            value: form.lessons,
            effectiveText: null,
            hintKey: 'lessons.hint',
            destructive: true,
            placeholder: projectValue('lessons'),
            onChange: (value) => { change('lessons', value) },
          }),
          h('div', { style: S.field },
            head(t, 'mode.label', null),
            h(SegmentedControl, {
              id: 'dsh-worklog-mode',
              value: form.mode,
              options: modeOptions,
              label: t('mode.control'),
              disabled: phase === 'pending',
              onChange: (next) => { change('mode', next) },
            }),
            h('p', { style: S.hint }, t('mode.hint'))))),

        h('p', { style: S.hint }, t('restart')),
        h('p', { style: S.footer },
          t('file.label') + '：',
          filePath === '' ? t('state.loading') : h('code', { style: S.code }, filePath),
          fileError !== null ? ' ' + t('file.broken') : null),
        h('p', { style: S.footer },
          // 只留兼容性提醒：重启那件事由上面那行按字段说清楚了，这里再笼统说一遍
          // 会把"新项目默认值也要重启才生效"重新说回来。
          t('spec.note') + '改名类字段（' + t('container.label') + ' / '
          + t('lessons.label') + '）对已有项目是破坏性的。'))
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
