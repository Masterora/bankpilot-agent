/**
 * 文件职责：将页面已取得的导出内容保存为文件，统一释放临时对象 URL。
 * 关键边界：不请求 API，不转换业务数据；文件内容、名称和类型由调用方决定。
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
