/**
 * 文件职责：集中管理 BankPilot Web 的中英文文案与语言偏好。
 *
 * 主要内容：
 * - `Messages`：约束每种语言必须实现的界面文案。
 * - `zhCN` / `enUS`：注册、登录、卡片、账单导入、统计、异常、分类和事件文案。
 * - `storedLocale`：读取持久化语言，异常值回退为中文。
 * - `isPresetQuery`：识别可随语言切换的预设查询。
 *
 * 关键边界：切换语言只替换预设查询，不覆盖用户自行输入的文本。
 */

import type { BillAnomaly, Card, Run, TransactionCategory } from './types'
import type { ProductPage } from './app/pages'

export type { ProductPage } from './app/pages'

export type Locale = 'zh-CN' | 'en-US'

export interface ProductPageCopy {
  navigation: string
  eyebrow: string
  title: string
  description: string
  empty: string
}

export interface ImportCopy {
  chooseFile: string
  fileRequirements: string
  csvOnly: string
  fileTooLarge: string
  missingHeader: string
  fileReadFailed: string
  accountName: string
  accountPlaceholder: string
  currency: string
  currencyPlaceholder: string
  mappingEyebrow: string
  mappingHeading: string
  columns: string
  pending: string
  mappingEmpty: string
  occurredAt: string
  merchant: string
  amount: string
  description: string
  selectColumn: string
  notMapped: string
  duplicateMapping: string
  commit: string
  importing: string
  importFailed: string
  conflict: string
  reportEyebrow: string
  reportHeading: string
  totalRows: string
  importedRows: string
  duplicateRows: string
  errorRows: string
  row: string
  historyEyebrow: string
  historyHeading: string
  loading: string
  loadFailed: string
  file: string
  period: string
  status: string
  statuses: Record<'COMPLETED' | 'COMPLETED_WITH_DUPLICATES' | 'REJECTED' | 'REVOKED', string>
  errorCodes: Record<string, string>
}

export interface Messages {
  languageLabel: string
  switchToChinese: string
  switchToEnglish: string
  checkingSession: string
  loginHeading: string
  loginHint: string
  registerHint: string
  email: string
  password: string
  confirmPassword: string
  passwordRequirement: string
  login: string
  loggingIn: string
  register: string
  registering: string
  loginFailed: string
  registerFailed: string
  invalidCredentials: string
  emailAlreadyRegistered: string
  passwordMismatch: string
  cardsEyebrow: string
  cardsHeading: string
  cardsLoading: string
  cardsEmpty: string
  cardsLoadFailed: string
  cardEnding: string
  cardStatuses: Record<Card['status'], string>
  navigationLabel: string
  readOnlyScope: string
  localDataScope: string
  productPages: Record<ProductPage, ProductPageCopy>
  linkedCardsMetric: string
  transactionsMetric: string
  reviewSignalsMetric: string
  latestRunMetric: string
  noRunStatus: string
  quickTasksHeading: string
  openAgent: string
  openReview: string
  auditBoundaryHeading: string
  auditEventsHeading: string
  sourceDataBoundary: string
  sourceDataBoundaryDetail: string
  modelBoundary: string
  modelBoundaryDetail: string
  accountBoundary: string
  accountBoundaryDetail: string
  secretBoundary: string
  secretBoundaryDetail: string
  queryInputLabel: string
  queryShortcut: string
  defaultQuery: string
  suggestions: readonly string[]
  querying: string
  startQuery: string
  queryStatusFailed: string
  createRunFailed: string
  logout: string
  emptyResult: string
  resultEyebrow: string
  timelineEyebrow: string
  analysisEyebrow: string
  incomeLabel: string
  expenseLabel: string
  netLabel: string
  categoryBreakdown: string
  anomalyHeading: string
  noAnomalies: string
  categoryLabel: string
  categoryUpdateFailed: string
  imports: ImportCopy
  categoryLabels: Record<TransactionCategory, string>
  anomalyDescription: (anomaly: BillAnomaly) => string
  statuses: Record<Run['status'], string>
  events: Record<string, string>
  resultSummary: (startDate: string, endDate: string, count: number) => string
}

const zhCN: Messages = {
  languageLabel: '语言',
  switchToChinese: '切换为中文',
  switchToEnglish: 'Switch to English',
  checkingSession: '会话验证中',
  loginHeading: 'BankPilot',
  loginHint: '本地财务核查',
  registerHint: '创建财务工作区',
  email: '邮箱',
  password: '密码',
  confirmPassword: '确认密码',
  passwordRequirement: '至少 12 位',
  login: '登录',
  loggingIn: '验证中…',
  register: '注册',
  registering: '创建中…',
  loginFailed: '登录失败',
  registerFailed: '注册失败',
  invalidCredentials: '凭证无效',
  emailAlreadyRegistered: '该邮箱已注册',
  passwordMismatch: '两次输入的密码不一致',
  cardsEyebrow: '账户范围',
  cardsHeading: '关联卡片',
  cardsLoading: '账户载入中…',
  cardsEmpty: '暂无关联卡片',
  cardsLoadFailed: '账户载入失败',
  cardEnding: '尾号',
  cardStatuses: { ACTIVE: '有效', LOCKED: '锁定' },
  navigationLabel: '工作区',
  readOnlyScope: '只读执行',
  localDataScope: '本地数据写入',
  productPages: {
    overview: {
      navigation: '财务总览',
      eyebrow: '财务工作区',
      title: '财务总览',
      description: '账户范围 · 核查状态 · 任务入口',
      empty: '',
    },
    agent: {
      navigation: 'Agent 工作台',
      eyebrow: '受控财务 Agent',
      title: 'Agent 工作台',
      description: '任务解析 · 白名单工具 · 执行证据',
      empty: '',
    },
    import: {
      navigation: '账单导入',
      eyebrow: '账单文件',
      title: '账单导入',
      description: '文件校验 · 字段映射 · 归一化',
      empty: '暂无导入批次',
    },
    review: {
      navigation: '交易账本',
      eyebrow: '确定性分析',
      title: '交易账本',
      description: '收支统计 · 异常信号 · 交易证据',
      empty: '暂无核查结果',
    },
    recurring: { navigation: '周期扣款', eyebrow: '周期信号', title: '周期扣款', description: '扣款周期 · 金额变化 · 预计日期', empty: '暂无周期扣款记录' },
    budgets: { navigation: '预算监控', eyebrow: '预算偏差', title: '预算监控', description: '已入账支出 · 阈值信号 · 确认变更', empty: '暂无预算记录' },
    audit: {
      navigation: '数据与审计',
      eyebrow: '系统治理',
      title: '数据与审计',
      description: '数据边界 · Agent 调用 · 执行记录',
      empty: '暂无执行记录',
    },
  },
  linkedCardsMetric: '关联卡片',
  transactionsMetric: '最近交易',
  reviewSignalsMetric: '待核查信号',
  latestRunMetric: '最近运行',
  noRunStatus: '无记录',
  quickTasksHeading: '任务入口',
  openAgent: '发起核查',
  openReview: '查看结果',
  auditBoundaryHeading: '数据边界',
  auditEventsHeading: 'Agent 审计',
  sourceDataBoundary: '原始账单',
  sourceDataBoundaryDetail: '原文件不保存 · 标准交易进入自托管 PostgreSQL',
  modelBoundary: 'OpenRouter',
  modelBoundaryDetail: '仅接收任务与规划所需信息',
  accountBoundary: '账户信息',
  accountBoundaryDetail: '账本账户名称与币种',
  secretBoundary: '模型密钥',
  secretBoundaryDetail: '服务端环境注入 · 不进入代码与镜像',
  queryInputLabel: '核查任务',
  queryShortcut: '⌘ / Ctrl + Enter 提交',
  defaultQuery: '核查本月交易',
  suggestions: ['核查本月交易', '核查近 7 天交易', '核查上月交易'],
  querying: '运行中…',
  startQuery: '开始',
  queryStatusFailed: '运行状态读取失败',
  createRunFailed: '运行创建失败',
  logout: '退出',
  emptyResult: '暂无核查结果',
  resultEyebrow: '核查结果',
  timelineEyebrow: '执行链',
  analysisEyebrow: '确定性统计',
  incomeLabel: '流入',
  expenseLabel: '流出',
  netLabel: '净额',
  categoryBreakdown: '分类构成',
  anomalyHeading: '待核查',
  noAnomalies: '未发现异常信号',
  categoryLabel: '交易分类',
  categoryUpdateFailed: '分类修正失败',
  imports: {
    chooseFile: '选择 CSV 账单',
    fileRequirements: 'CSV · 最大 10 MB · 原文件不保存',
    csvOnly: '仅支持 CSV 文件',
    fileTooLarge: '文件超过 10 MB 限制',
    missingHeader: '未识别到 CSV 表头',
    fileReadFailed: '文件读取失败',
    accountName: '账户名称',
    accountPlaceholder: '例如：日常账户',
    currency: '币种',
    currencyPlaceholder: '例如：CNY',
    mappingEyebrow: '标准字段',
    mappingHeading: '字段映射',
    columns: '列',
    pending: '等待文件',
    mappingEmpty: '选择文件后配置字段映射',
    occurredAt: '交易日期',
    merchant: '交易对方',
    amount: '带符号金额',
    description: '说明',
    selectColumn: '选择源列',
    notMapped: '不映射',
    duplicateMapping: '每个标准字段必须对应不同源列',
    commit: '校验并导入',
    importing: '正在校验',
    importFailed: '账单导入失败',
    conflict: '数据冲突，请检查交易编号与已导入记录后重试',
    reportEyebrow: '批次结果',
    reportHeading: '导入报告',
    totalRows: '总行数',
    importedRows: '已写入',
    duplicateRows: '重复',
    errorRows: '失败',
    row: '第',
    historyEyebrow: '导入记录',
    historyHeading: '导入历史',
    loading: '正在读取导入历史',
    loadFailed: '导入历史读取失败',
    file: '文件',
    period: '交易期间',
    status: '状态',
    statuses: {
      COMPLETED: '已完成',
      COMPLETED_WITH_DUPLICATES: '已去重',
      REJECTED: '已拒绝',
      REVOKED: '已撤销',
    },
    errorCodes: {
      EMPTY_FILE: '文件为空',
      INVALID_ENCODING: '文件编码无效，请使用 UTF-8',
      DUPLICATE_HEADER: '表头包含重复列',
      MISSING_COLUMN: '缺少已映射的源列',
      NO_DATA_ROWS: '文件中没有交易记录',
      TOO_MANY_ROWS: '交易行数超过 5,000 行',
      INVALID_ROW: '该行字段格式无效',
    },
  },
  categoryLabels: {
    income: '收入',
    groceries: '日用百货',
    dining: '餐饮',
    transport: '交通',
    shopping: '购物',
    housing: '住房',
    utilities: '生活缴费',
    entertainment: '娱乐',
    healthcare: '医疗',
    education: '教育',
    travel: '旅行',
    transfer: '转账',
    other: '其他',
  },
  anomalyDescription: (anomaly) =>
    anomaly.rule_id === 'large_outflow_v1'
      ? `大额支出 · ${anomaly.facts.amount} ${anomaly.facts.currency} · 阈值 ${anomaly.facts.threshold}`
      : `${anomaly.facts.merchant} · ${anomaly.facts.amount} ${anomaly.facts.currency} · ${anomaly.facts.window_minutes} 分钟内重复`,
  statuses: {
    CREATED: '已创建',
    PLANNING: '规划中',
    EXECUTING: '执行中',
    SUCCEEDED: '完成',
    FAILED: '失败',
    UNKNOWN: '状态未知',
  },
  events: {
    'run.created': '运行已创建',
    'run.planning': '范围解析',
    'tool.started': '交易查询',
    'tool.completed': '查询完成',
    'analysis.completed': '确定性分析',
    'transaction.category_corrected': '交易分类已修正',
    'run.completed': '运行完成',
    'run.failed': '运行失败',
  },
  resultSummary: (startDate, endDate, count) => `${startDate} — ${endDate} · ${count} 笔`,
}

const enUS: Messages = {
  languageLabel: 'Language',
  switchToChinese: '切换为中文',
  switchToEnglish: 'Switch to English',
  checkingSession: 'Validating session',
  loginHeading: 'BankPilot',
  loginHint: 'Local financial review',
  registerHint: 'Create a financial workspace',
  email: 'Email',
  password: 'Password',
  confirmPassword: 'Confirm password',
  passwordRequirement: '12 characters minimum',
  login: 'Sign in',
  loggingIn: 'Validating…',
  register: 'Register',
  registering: 'Creating…',
  loginFailed: 'Sign-in failed',
  registerFailed: 'Registration failed',
  invalidCredentials: 'Invalid credentials',
  emailAlreadyRegistered: 'Email is already registered',
  passwordMismatch: 'Passwords do not match',
  cardsEyebrow: 'ACCOUNT SCOPE',
  cardsHeading: 'Linked cards',
  cardsLoading: 'Loading cards…',
  cardsEmpty: 'No cards available',
  cardsLoadFailed: 'Unable to load cards',
  cardEnding: 'Ending in',
  cardStatuses: { ACTIVE: 'Active', LOCKED: 'Locked' },
  navigationLabel: 'Workspace',
  readOnlyScope: 'Read-only execution',
  localDataScope: 'Local data write',
  productPages: {
    overview: {
      navigation: 'Overview',
      eyebrow: 'FINANCE WORKSPACE',
      title: 'Financial overview',
      description: 'Account scope · Review status · Task entry points',
      empty: '',
    },
    agent: {
      navigation: 'Agent workspace',
      eyebrow: 'GOVERNED FINANCE AGENT',
      title: 'Agent workspace',
      description: 'Task parsing · Allowlisted tools · Execution evidence',
      empty: '',
    },
    import: {
      navigation: 'Statement import',
      eyebrow: 'LOCAL DATA ENTRY',
      title: 'Statement import',
      description: 'File validation · Field mapping · Normalization',
      empty: 'No import batches',
    },
    review: {
      navigation: 'Statement review',
      eyebrow: 'DETERMINISTIC ANALYSIS',
      title: 'Statement review',
      description: 'Cash flow · Review signals · Transaction evidence',
      empty: 'No review result',
    },
    recurring: { navigation: 'Recurring charges', eyebrow: 'RECURRING SIGNALS', title: 'Recurring charges', description: 'Cadence · Amount changes · Expected dates', empty: 'No recurring charge records' },
    budgets: { navigation: 'Budget monitoring', eyebrow: 'BUDGET VARIANCE', title: 'Budget monitoring', description: 'Posted spend · Threshold signals · Confirmed changes', empty: 'No budget records' },
    audit: {
      navigation: 'Data & audit',
      eyebrow: 'SYSTEM GOVERNANCE',
      title: 'Data & audit',
      description: 'Data boundaries · Agent calls · Execution records',
      empty: 'No execution records',
    },
  },
  linkedCardsMetric: 'Linked cards',
  transactionsMetric: 'Latest transactions',
  reviewSignalsMetric: 'Review signals',
  latestRunMetric: 'Latest run',
  noRunStatus: 'No record',
  quickTasksHeading: 'Task entry points',
  openAgent: 'Start review',
  openReview: 'View result',
  auditBoundaryHeading: 'Data boundaries',
  auditEventsHeading: 'Agent audit',
  sourceDataBoundary: 'Source statements',
  sourceDataBoundaryDetail: 'Source file discarded · Normalized records are self-hosted',
  modelBoundary: 'OpenRouter',
  modelBoundaryDetail: 'Receives task and planning context only',
  accountBoundary: 'Account data',
  accountBoundaryDetail: 'Ledger account name and currency',
  secretBoundary: 'Model secret',
  secretBoundaryDetail: 'Server environment only · Excluded from code and images',
  queryInputLabel: 'Review task',
  queryShortcut: '⌘ / Ctrl + Enter to submit',
  defaultQuery: 'Review transactions this month',
  suggestions: [
    'Review transactions this month',
    'Review transactions from the last 7 days',
    'Review transactions from last month',
  ],
  querying: 'Running…',
  startQuery: 'Start',
  queryStatusFailed: 'Unable to read run status',
  createRunFailed: 'Unable to create run',
  logout: 'Sign out',
  emptyResult: 'No review result',
  resultEyebrow: 'REVIEW RESULT',
  timelineEyebrow: 'EXECUTION TRACE',
  analysisEyebrow: 'DETERMINISTIC SUMMARY',
  incomeLabel: 'Inflow',
  expenseLabel: 'Outflow',
  netLabel: 'Net',
  categoryBreakdown: 'Category mix',
  anomalyHeading: 'Review signals',
  noAnomalies: 'No anomaly rules matched',
  categoryLabel: 'Transaction category',
  categoryUpdateFailed: 'Unable to update category',
  imports: {
    chooseFile: 'Choose CSV statement',
    fileRequirements: 'CSV · 10 MB maximum · Source file not retained',
    csvOnly: 'Only CSV files are supported',
    fileTooLarge: 'File exceeds the 10 MB limit',
    missingHeader: 'CSV header could not be detected',
    fileReadFailed: 'Unable to read the file',
    accountName: 'Account name',
    accountPlaceholder: 'e.g. Daily account',
    currency: 'Currency',
    currencyPlaceholder: 'e.g. USD',
    mappingEyebrow: 'STANDARD FIELDS',
    mappingHeading: 'Field mapping',
    columns: 'columns',
    pending: 'Awaiting file',
    mappingEmpty: 'Choose a file to configure field mapping',
    occurredAt: 'Transaction date',
    merchant: 'Merchant',
    amount: 'Signed amount',
    description: 'Description',
    selectColumn: 'Select source column',
    notMapped: 'Not mapped',
    duplicateMapping: 'Each standard field must use a different source column',
    commit: 'Validate and import',
    importing: 'Validating',
    importFailed: 'Statement import failed',
    conflict: 'Import conflict. Check transaction identifiers against saved records before retrying.',
    reportEyebrow: 'BATCH RESULT',
    reportHeading: 'Import report',
    totalRows: 'Total rows',
    importedRows: 'Imported',
    duplicateRows: 'Duplicates',
    errorRows: 'Failed',
    row: 'Row',
    historyEyebrow: 'LOCAL BATCHES',
    historyHeading: 'Import history',
    loading: 'Loading import history',
    loadFailed: 'Unable to load import history',
    file: 'File',
    period: 'Period',
    status: 'Status',
    statuses: {
      COMPLETED: 'Completed',
      COMPLETED_WITH_DUPLICATES: 'Deduplicated',
      REJECTED: 'Rejected',
      REVOKED: 'Revoked',
    },
    errorCodes: {
      EMPTY_FILE: 'The file is empty',
      INVALID_ENCODING: 'Invalid encoding; use UTF-8',
      DUPLICATE_HEADER: 'The header contains duplicate columns',
      MISSING_COLUMN: 'A mapped source column is missing',
      NO_DATA_ROWS: 'The file contains no transactions',
      TOO_MANY_ROWS: 'The file exceeds 5,000 transaction rows',
      INVALID_ROW: 'The row contains an invalid field',
    },
  },
  categoryLabels: {
    income: 'Income',
    groceries: 'Groceries',
    dining: 'Dining',
    transport: 'Transport',
    shopping: 'Shopping',
    housing: 'Housing',
    utilities: 'Utilities',
    entertainment: 'Entertainment',
    healthcare: 'Healthcare',
    education: 'Education',
    travel: 'Travel',
    transfer: 'Transfer',
    other: 'Other',
  },
  anomalyDescription: (anomaly) =>
    anomaly.rule_id === 'large_outflow_v1'
      ? `Large expense · ${anomaly.facts.amount} ${anomaly.facts.currency} · threshold ${anomaly.facts.threshold}`
      : `${anomaly.facts.merchant} · ${anomaly.facts.amount} ${anomaly.facts.currency} · repeated within ${anomaly.facts.window_minutes} min`,
  statuses: {
    CREATED: 'Created',
    PLANNING: 'Planning',
    EXECUTING: 'Querying',
    SUCCEEDED: 'Complete',
    FAILED: 'Failed',
    UNKNOWN: 'Unknown',
  },
  events: {
    'run.created': 'Run created',
    'run.planning': 'Scope parsed',
    'tool.started': 'Transaction query',
    'tool.completed': 'Query complete',
    'analysis.completed': 'Deterministic analysis',
    'transaction.category_corrected': 'Transaction category corrected',
    'run.completed': 'Run complete',
    'run.failed': 'Run failed',
  },
  resultSummary: (startDate, endDate, count) =>
    `${startDate} — ${endDate} · ${count} transaction${count === 1 ? '' : 's'}`,
}

export const messages: Record<Locale, Messages> = {
  'zh-CN': zhCN,
  'en-US': enUS,
}

export function storedLocale(): Locale {
  // 未知或缺失的配置统一回退到产品默认的中文。
  return window.localStorage.getItem('bankpilot.locale') === 'en-US' ? 'en-US' : 'zh-CN'
}

export function isPresetQuery(message: string): boolean {
  // 切换语言时可替换预设文案，但必须保留用户自行输入的内容。
  return Object.values(messages).some((copy) =>
    [copy.defaultQuery, ...copy.suggestions].includes(message),
  )
}
