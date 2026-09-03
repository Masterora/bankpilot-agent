/**
 * 文件职责：初始化 Web 测试运行环境。
 * 主要内容：注册 Testing Library 的 DOM 断言扩展。
 * 关键边界：由 Vitest `setupFiles` 统一加载，不应被生产入口引用。
 */

import '@testing-library/jest-dom/vitest'
