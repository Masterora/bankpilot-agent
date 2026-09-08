/**
 * 文件职责：声明当前可访问的产品页面与权限表现。
 *
 * 主要内容：`pageDefinitions` 统一声明页面类型和当前导航可见性。
 * 关键边界：未接入能力保留页面结构和导航入口，但不模拟数据或操作。
 */

export const pageDefinitions = [
  { id: 'overview', visible: true },
  { id: 'import', visible: true },
  { id: 'review', visible: true },
  { id: 'relations', visible: true },
  { id: 'agent', visible: true },
  { id: 'reports', visible: true },
  { id: 'recurring', visible: true },
  { id: 'budgets', visible: true },
  { id: 'audit', visible: true },
] as const

export type ProductPage = (typeof pageDefinitions)[number]['id']

/** 按任务而非实现顺序分组；规划中的入口仍可访问其状态页面。 */
export const navigationGroups: { id: string; pages: ProductPage[] }[] = [
  { id: 'ledger', pages: ['overview', 'import', 'review', 'relations'] },
  { id: 'analysis', pages: ['agent', 'audit'] },
  { id: 'planning', pages: ['reports', 'recurring', 'budgets'] },
]
