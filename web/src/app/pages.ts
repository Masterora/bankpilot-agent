/** 声明当前可访问的产品页面与权限表现。
 * 页面标识保持稳定，支持浏览器地址恢复。
 */

export const pageDefinitions = [
  'overview',
  'import',
  'review',
  'relations',
  'agent',
  'reports',
  'recurring',
  'budgets',
  'audit',
  'settings',
] as const

export type ProductPage = (typeof pageDefinitions)[number]

/** 常用任务优先；导入、核对与运行记录保留在工具区。 */
export const primaryPages: ProductPage[] = ['overview', 'review', 'budgets', 'recurring', 'reports']
export const secondaryPages: ProductPage[] = ['import', 'agent', 'relations', 'audit']
