/**
 * 文件职责：配置 Web 的 Vite 开发/构建环境与 Vitest 测试环境。
 *
 * 主要内容：React 插件、本地 `/api` 反向代理、jsdom 测试环境与测试初始化文件。
 * 关键边界：代理仅服务于本地开发，生产 API 转发由 Nginx 配置负责。
 */

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
})
