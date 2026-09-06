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
  { id: 'agent', visible: true },
  { id: 'recurring', visible: true },
  { id: 'budgets', visible: true },
  { id: 'audit', visible: true },
] as const

export type ProductPage = (typeof pageDefinitions)[number]['id']
