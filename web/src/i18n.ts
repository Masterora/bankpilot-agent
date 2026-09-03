/**
 * 文件职责：集中管理 BankPilot Web 的中英文文案与语言偏好。
 *
 * 主要内容：
 * - `Messages`：约束每种语言必须实现的界面文案。
 * - `zhCN` / `enUS`：登录、工作台、状态、事件和结果文案。
 * - `storedLocale`：读取持久化语言，异常值回退为中文。
 * - `isPresetQuery`：识别可随语言切换的预设查询。
 *
 * 关键边界：切换语言只替换预设查询，不覆盖用户自行输入的文本。
 */

import type { Run } from './types'

export type Locale = 'zh-CN' | 'en-US'

export interface Messages {
  languageLabel: string
  switchToChinese: string
  switchToEnglish: string
  checkingSession: string
  loginEyebrow: string
  loginTitle: string
  loginDescription: string
  securityNote: string
  secureAccess: string
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
  statuses: Record<Run['status'], string>
  events: Record<string, string>
  resultSummary: (startDate: string, endDate: string, count: number) => string
}

const zhCN: Messages = {
  languageLabel: '语言',
  switchToChinese: '切换为中文',
  switchToEnglish: 'Switch to English',
  checkingSession: '正在检查会话',
  loginEyebrow: 'BANKING, WITH INTENT',
  loginTitle: '说出目标，\n清楚完成每一步。',
  loginDescription: 'Agent 理解你的银行意图，确定性程序负责数据、权限与执行边界。',
  securityNote: '本地银行数据 · 可追溯运行记录 · 严格工具白名单',
  secureAccess: '安全访问',
  loginHeading: '登录 BankPilot',
  loginHint: '使用本地账户继续。',
  email: '邮箱',
  password: '密码',
  login: '登录',
  loggingIn: '正在登录…',
  loginFailed: '登录失败，请稍后重试',
  invalidCredentials: '邮箱或密码错误',
  workspaceEyebrow: '只读账单工作台',
  workspaceTitle: '今天想查什么？',
  workspaceDescription: '使用自然语言指定时间范围，BankPilot 会规划并查询你的本地账单。',
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
  loginEyebrow: 'BANKING, WITH INTENT',
  loginTitle: 'State your goal.\nSee every step clearly.',
  loginDescription:
    'The Agent understands your banking intent while deterministic code controls data, permissions, and execution.',
  securityNote: 'Local banking data · Traceable runs · Strict tool allowlist',
  secureAccess: 'SECURE ACCESS',
  loginHeading: 'Sign in to BankPilot',
  loginHint: 'Continue with your local account.',
  email: 'Email',
  password: 'Password',
  login: 'Sign in',
  loggingIn: 'Signing in…',
  loginFailed: 'Sign-in failed. Please try again.',
  invalidCredentials: 'Incorrect email or password',
  workspaceEyebrow: 'READ-ONLY BILLING WORKSPACE',
  workspaceTitle: 'What would you like to check?',
  workspaceDescription:
    'Describe a date range in natural language. BankPilot will plan and query your local transactions.',
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
