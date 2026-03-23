interface Props {
  type: 'NOT_FOUND' | 'NETWORK_ERROR'
}

export default function ErrorScreen({ type }: Props) {
  const isNotFound = type === 'NOT_FOUND'
  return (
    <div className="status-screen">
      <div className="error-icon">{isNotFound ? '🔍' : '⚠️'}</div>
      <h2>{isNotFound ? '报告不存在' : '加载失败'}</h2>
      <p>{isNotFound ? '该报告不存在或尚未准备就绪' : '网络错误，请稍后重试'}</p>
    </div>
  )
}
