/**
 * 文件职责：启动并挂载 BankPilot React 应用。
 *
 * 主要内容：加载全局样式，在 `root` 节点下以 `StrictMode` 渲染 `App`。
 * 关键边界：本文件只负责应用启动，不承载业务状态。
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
