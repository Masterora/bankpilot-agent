/**
 * 文件职责：配置 Web 的 Vite 开发/构建环境与 Vitest 测试环境。
 *
 * 主要内容：React 插件、Tailscale 远程 API 开发代理、jsdom 测试环境与测试初始化文件。
 * 关键边界：浏览器始终请求同源 `/api`；远程地址只从仓库根目录的本地环境变量读取，不进入前端产物。
 */

import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, '..', 'BANKPILOT_')
  const remoteOrigin = env.BANKPILOT_REMOTE_ORIGIN?.trim()

  // 开发服务器必须显式连接远程 Tailscale 入口，避免静默回退到不存在的本机 API。
  if (command === 'serve' && mode === 'development' && !remoteOrigin) {
    throw new Error('BANKPILOT_REMOTE_ORIGIN is required for local Web development')
  }

  if (remoteOrigin && !/^https?:\/\/[^/]+(?::\d+)?$/.test(remoteOrigin)) {
    throw new Error('BANKPILOT_REMOTE_ORIGIN must be an HTTP(S) origin without a path')
  }

  return {
    envDir: '..',
    plugins: [react()],
    server: {
      proxy: remoteOrigin
        ? {
            '/api': {
              target: remoteOrigin,
              changeOrigin: true,
            },
          }
        : undefined,
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
    },
  }
})
