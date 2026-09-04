/**
 * 文件职责：集中管理 BankPilot Web 的中英文文案与语言偏好。
 *
 * 主要内容：
 * - `Messages`：约束每种语言必须实现的界面文案。
 * - `zhCN` / `enUS`：登录、工作台、统计、异常、分类和事件文案。
 * - `storedLocale`：读取持久化语言，异常值回退为中文。
 * - `isPresetQuery`：识别可随语言切换的预设查询。
 *
 * 关键边界：切换语言只替换预设查询，不覆盖用户自行输入的文本。
 */

import type { BillAnomaly, Run, TransactionCategory } from './types'

export type Locale = 'zh-CN' | 'en-US'

export interface Messages {
  languageLabel: string
  switchToChinese: string
  switchToEnglish: string
  checkingSession: string
  loginHeading: string
  loginHint: string
  email: string
  password: string
  login: string
  loggingIn: string
  loginFailed: string
  invalidCredentials: string
  workspaceEyebrow: string
  workspaceTitle: string
  workspaceDescription: string
  queryInputLabel: string
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
  checkingSession: '正在检查会话',
  loginHeading: '登录 BankPilot',
  loginHint: '使用本地账户访问账单分析。',
  email: '邮箱',
  password: '密码',
  login: '登录',
  loggingIn: '正在登录…',
  loginFailed: '登录失败，请稍后重试',
  invalidCredentials: '邮箱或密码错误',
  workspaceEyebrow: '账单分析',
  workspaceTitle: '查询账单',
  workspaceDescription: '输入时间范围，查看分类、统计和异常。',
  queryInputLabel: '账单查询',
  defaultQuery: '查询本月账单',
  suggestions: ['查询本月账单', '查看最近 7 天的交易', '查询上个月的账单'],
  querying: '处理中…',
  startQuery: '开始查询',
  queryStatusFailed: '无法读取任务状态',
  createRunFailed: '任务创建失败',
  logout: '退出',
  emptyResult: '查询结果会显示在这里',
  resultEyebrow: '运行结果',
  timelineEyebrow: '操作记录',
  analysisEyebrow: '确定性统计',
  incomeLabel: '收入',
  expenseLabel: '支出',
  netLabel: '净额',
  categoryBreakdown: '分类构成',
  anomalyHeading: '异常提示',
  noAnomalies: '未命中异常规则',
  categoryLabel: '交易分类',
  categoryUpdateFailed: '分类修正失败，请重试',
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
      ? `单笔支出 ${anomaly.facts.amount} ${anomaly.facts.currency}，达到规则阈值 ${anomaly.facts.threshold}。`
      : `${anomaly.facts.merchant} 在 ${anomaly.facts.window_minutes} 分钟内出现相同扣款 ${anomaly.facts.amount} ${anomaly.facts.currency}。`,
  statuses: {
    CREATED: '已创建',
    PLANNING: '正在理解',
    EXECUTING: '正在查询',
    SUCCEEDED: '已完成',
    FAILED: '失败',
    UNKNOWN: '待处理',
  },
  events: {
    'run.created': '任务已创建',
    'run.planning': '理解查询范围',
    'tool.started': '开始查询账单',
    'tool.completed': '账单查询完成',
    'analysis.completed': '账单分析完成',
    'transaction.category_corrected': '交易分类已修正',
    'run.completed': '结果已确认',
    'run.failed': '任务未完成',
  },
  resultSummary: (startDate, endDate, count) =>
    `已查询 ${startDate} 至 ${endDate} 的账单，共 ${count} 笔。`,
}

const enUS: Messages = {
  languageLabel: 'Language',
  switchToChinese: '切换为中文',
  switchToEnglish: 'Switch to English',
  checkingSession: 'Checking your session',
  loginHeading: 'Sign in to BankPilot',
  loginHint: 'Use your local account to access bill analysis.',
  email: 'Email',
  password: 'Password',
  login: 'Sign in',
  loggingIn: 'Signing in…',
  loginFailed: 'Sign-in failed. Please try again.',
  invalidCredentials: 'Incorrect email or password',
  workspaceEyebrow: 'BILL ANALYSIS',
  workspaceTitle: 'Query transactions',
  workspaceDescription: 'Enter a date range to see categories, totals, and anomalies.',
  queryInputLabel: 'Transaction query',
  defaultQuery: 'Show my transactions this month',
  suggestions: [
    'Show my transactions this month',
    'Show transactions from the last 7 days',
    'Show my transactions from last month',
  ],
  querying: 'Working…',
  startQuery: 'Run query',
  queryStatusFailed: 'Unable to retrieve the run status',
  createRunFailed: 'Unable to create the run',
  logout: 'Sign out',
  emptyResult: 'Your query results will appear here',
  resultEyebrow: 'RUN RESULT',
  timelineEyebrow: 'ACTIVITY',
  analysisEyebrow: 'DETERMINISTIC SUMMARY',
  incomeLabel: 'Income',
  expenseLabel: 'Expense',
  netLabel: 'Net',
  categoryBreakdown: 'Category mix',
  anomalyHeading: 'Anomaly signals',
  noAnomalies: 'No anomaly rules matched',
  categoryLabel: 'Transaction category',
  categoryUpdateFailed: 'Unable to update the category. Please retry.',
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
      ? `A ${anomaly.facts.amount} ${anomaly.facts.currency} expense met the ${anomaly.facts.threshold} rule threshold.`
      : `${anomaly.facts.merchant} posted the same ${anomaly.facts.amount} ${anomaly.facts.currency} charge within ${anomaly.facts.window_minutes} minutes.`,
  statuses: {
    CREATED: 'Created',
    PLANNING: 'Planning',
    EXECUTING: 'Querying',
    SUCCEEDED: 'Complete',
    FAILED: 'Failed',
    UNKNOWN: 'Needs attention',
  },
  events: {
    'run.created': 'Run created',
    'run.planning': 'Interpreted date range',
    'tool.started': 'Started transaction query',
    'tool.completed': 'Transaction query completed',
    'analysis.completed': 'Bill analysis completed',
    'transaction.category_corrected': 'Transaction category corrected',
    'run.completed': 'Result confirmed',
    'run.failed': 'Run did not complete',
  },
  resultSummary: (startDate, endDate, count) =>
    `Found ${count} transaction${count === 1 ? '' : 's'} from ${startDate} to ${endDate}.`,
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
