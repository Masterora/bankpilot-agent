/**
 * 文件职责：配置 Web 的 Vite 开发与生产构建环境。
 *
 * 主要内容：React 插件、本地 API 开发代理和生产构建。
 * 关键边界：浏览器始终请求同源 `/api`；代理地址由根目录环境变量配置，不进入前端产物。
 */

import react from '@vitejs/plugin-react'
import { loadEnv, defineConfig } from 'vite'

export default defineConfig(({ command, mode }) => {
  // 只有本地开发代理读取运行配置；测试和生产构建不依赖本地环境文件。
  const env = command === 'serve' && mode === 'development'
    ? loadEnv(mode, '..', 'BANKPILOT_')
    : {}
  const apiOrigin = env.BANKPILOT_API_ORIGIN?.trim() || 'http://127.0.0.1:8000'

  if (!/^https?:\/\/[^/]+(?::\d+)?$/.test(apiOrigin)) {
    throw new Error('BANKPILOT_API_ORIGIN must be an HTTP(S) origin without a path')
  }

  return {
    envDir: '..',
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': {
          target: apiOrigin,
          changeOrigin: true,
        },
      },
    },
  }
})
