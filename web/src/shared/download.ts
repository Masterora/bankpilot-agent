/**
 * 文件职责：将页面已取得的内容下载为文件。
 * 主要内容：创建 Blob、临时对象 URL 和下载链接，并释放资源。
 * 关键边界：不请求 API 或转换业务数据；内容、文件名和 MIME 类型由调用方提供。
 */
export function downloadFile(content: string, fileName: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  try {
    const link = document.createElement('a')
    link.href = url
    link.download = fileName
    link.click()
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
}
