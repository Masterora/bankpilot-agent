/**
 * 文件职责：声明当前可访问的产品页面与权限表现。
 *
 * 主要内容：`pageDefinitions` 是导航、页面渲染与数据作用域提示的唯一页面注册表。
 * 关键边界：保留产品导航与未实现页面的空态；业务能力以独立 feature 模块接入。
 */

export const pageDefinitions = [
  { id: 'overview', scope: 'read' },
  { id: 'agent', scope: 'read' },
  { id: 'import', scope: 'write' },
  { id: 'review', scope: 'write' },
  { id: 'recurring', scope: 'read' },
  { id: 'budgets', scope: 'read' },
  { id: 'audit', scope: 'read' },
] as const

export type ProductPage = (typeof pageDefinitions)[number]['id']
