/** 集中管理 BankPilot Web 的中英文文案与语言偏好。
 * 切换语言只替换预设查询，不覆盖用户自行输入的文本。
 */

import type { BillAnomaly, Run, TransactionCategory } from './types'
import type { ProductPage } from './app/pages'

export type { ProductPage } from './app/pages'

export type Locale = 'zh-CN' | 'en-US'

export interface ProductPageCopy {
  navigation: string
  title: string
}

export interface ImportCopy {
  chooseFile: string
  fileRequirements: string

  missingHeader: string
  fileReadFailed: string
  accountName: string
  accountPlaceholder: string
  currency: string
  currencyPlaceholder: string
  occurredAt: string
  merchant: string
  amount: string
  description: string
  selectColumn: string
  notMapped: string
  duplicateMapping: string
  importing: string
  importFailed: string
  conflict: string
  reportHeading: string
  totalRows: string
  importedRows: string
  duplicateRows: string
  errorRows: string
  row: string
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
  email: string
  password: string
  confirmPassword: string
  passwordRequirement: string
  passwordFormatInvalid: string
  login: string
  loggingIn: string
  register: string
  registering: string
  loginFailed: string
  registerFailed: string
  invalidCredentials: string
  emailAlreadyRegistered: string
  passwordMismatch: string
  navigationLabel: string
  productPages: Record<ProductPage, ProductPageCopy>

  openReview: string
  auditEventsHeading: string
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
  runEventsHeading: string
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
  email: '邮箱',
  password: '密码',
  confirmPassword: '确认密码',
  passwordRequirement: '8–128 位，包含大小写字母、数字和符号',
  passwordFormatInvalid: '密码须包含大写字母、小写字母、数字和符号',
  login: '登录',
  loggingIn: '验证中…',
  register: '注册',
  registering: '创建中…',
  loginFailed: '登录失败',
  registerFailed: '注册失败',
  invalidCredentials: '账号或密码错误',
  emailAlreadyRegistered: '该邮箱已注册',
  passwordMismatch: '两次输入的密码不一致',
  navigationLabel: '工作区',
  productPages: {
    overview: {
      navigation: '总览',
      title: '账单总览',
    },
    agent: {
      navigation: '智能核查',
      title: '智能核查',
    },
    import: {
      navigation: '账户与导入',
      title: '账户与导入',
    },
    review: {
      navigation: '账本',
      title: '交易账本',
    },
    relations: { navigation: '交易关系核对', title: '核对重复、转账与退款' },
    reports: { navigation: '月度报告', title: '月度报告' },
    recurring: { navigation: '固定支出', title: '固定支出' },
    budgets: { navigation: '预算', title: '预算' },
    settings: { navigation: '设置', title: '设置' },
    audit: {
      navigation: '运行记录',
      title: '运行记录',
    },
  },

  openReview: '查看结果',
  auditEventsHeading: '运行事件',
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
  runEventsHeading: '运行过程',
  incomeLabel: '流入',
  expenseLabel: '流出',
  netLabel: '净额',
  categoryBreakdown: '分类构成',
  anomalyHeading: '待核查',
  noAnomalies: '未发现异常信号',
  categoryLabel: '交易分类',
  categoryUpdateFailed: '分类修正失败',
  imports: {
    chooseFile: '选择账单文件',
    fileRequirements: 'CSV / XLSX · 最大 10 MB',

    missingHeader: '未识别到 CSV 表头',
    fileReadFailed: '文件读取失败',
    accountName: '账户名称',
    accountPlaceholder: '例如：日常账户',
    currency: '币种',
    currencyPlaceholder: '例如：CNY',
    occurredAt: '交易日期',
    merchant: '交易对方',
    amount: '带符号金额',
    description: '说明',
    selectColumn: '选择源列',
    notMapped: '不映射',
    duplicateMapping: '每个标准字段必须对应不同源列',
    importing: '正在校验',
    importFailed: '账单导入失败',
    conflict: '数据冲突，请检查交易编号与已导入记录后重试',
    reportHeading: '导入报告',
    totalRows: '总行数',
    importedRows: '已写入',
    duplicateRows: '重复',
    errorRows: '失败',
    row: '第',
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
  email: 'Email',
  password: 'Password',
  confirmPassword: 'Confirm password',
  passwordRequirement: '8–128 characters with uppercase, lowercase, number and symbol',
  passwordFormatInvalid: 'Use uppercase, lowercase, number and symbol',
  login: 'Sign in',
  loggingIn: 'Validating…',
  register: 'Register',
  registering: 'Creating…',
  loginFailed: 'Sign-in failed',
  registerFailed: 'Registration failed',
  invalidCredentials: 'Incorrect email or password',
  emailAlreadyRegistered: 'Email is already registered',
  passwordMismatch: 'Passwords do not match',
  navigationLabel: 'Workspace',
  productPages: {
    overview: {
      navigation: 'Overview',
      title: 'Statement overview',
    },
    agent: {
      navigation: 'Agent review',
      title: 'Agent review',
    },
    import: {
      navigation: 'Accounts & import',
      title: 'Accounts & import',
    },
    review: {
      navigation: 'Ledger',
      title: 'Ledger',
    },
    relations: { navigation: 'Relationships', title: 'Relationships' },
    reports: { navigation: 'Monthly reports', title: 'Monthly reports' },
    recurring: { navigation: 'Fixed expenses', title: 'Fixed expenses' },
    budgets: { navigation: 'Budgets', title: 'Budgets' },
    settings: { navigation: 'Settings', title: 'Settings' },
    audit: {
      navigation: 'Audit trail',
      title: 'Audit trail',
    },
  },

  openReview: 'View result',
  auditEventsHeading: 'Run events',
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
  runEventsHeading: 'Run events',
  incomeLabel: 'Inflow',
  expenseLabel: 'Outflow',
  netLabel: 'Net',
  categoryBreakdown: 'Category mix',
  anomalyHeading: 'Review signals',
  noAnomalies: 'No anomaly rules matched',
  categoryLabel: 'Transaction category',
  categoryUpdateFailed: 'Unable to update category',
  imports: {
    chooseFile: 'Choose statement file',
    fileRequirements: 'CSV / XLSX · 10 MB maximum',

    missingHeader: 'CSV header could not be detected',
    fileReadFailed: 'Unable to read the file',
    accountName: 'Account name',
    accountPlaceholder: 'e.g. Daily account',
    currency: 'Currency',
    currencyPlaceholder: 'e.g. USD',
    occurredAt: 'Transaction date',
    merchant: 'Merchant',
    amount: 'Signed amount',
    description: 'Description',
    selectColumn: 'Select source column',
    notMapped: 'Not mapped',
    duplicateMapping: 'Each standard field must use a different source column',
    importing: 'Validating',
    importFailed: 'Statement import failed',
    conflict:
      'Import conflict. Check transaction identifiers against saved records before retrying.',
    reportHeading: 'Import report',
    totalRows: 'Total rows',
    importedRows: 'Imported',
    duplicateRows: 'Duplicates',
    errorRows: 'Failed',
    row: 'Row',
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
