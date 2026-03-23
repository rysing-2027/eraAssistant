interface Props {
  name: string
  docUrl: string | null
}

export default function ReportHeader({ name, docUrl }: Props) {
  return (
    <header className="report-header">
      <div className="header-left">
        <div className="badge">ERA 产品体验评估</div>
        <h1>{name} 的评估报告</h1>
      </div>
      {docUrl && (
        <a href={docUrl} target="_blank" rel="noopener noreferrer" className="doc-link">
          📄 查看飞书原文档
        </a>
      )}
    </header>
  )
}
