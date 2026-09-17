/**
 * 文件职责：声明当前可访问的产品页面与权限表现。
 *
 * 主要内容：`pageDefinitions` 统一声明页面类型和当前导航可见性。
 * 关键边界：页面标识保持稳定，支持浏览器地址恢复。
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

/** 常用任务优先；导入、核对与运行记录保留在工具区。 */
export const primaryPages: ProductPage[] = ['overview', 'review', 'recurring', 'budgets', 'reports']
export const secondaryPages: ProductPage[] = ['import', 'relations', 'agent', 'audit']
