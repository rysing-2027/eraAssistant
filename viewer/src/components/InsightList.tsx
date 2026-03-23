interface Props {
  title: string
  icon: string
  items: string[] | undefined
}

export default function InsightList({ title, icon, items }: Props) {
  return (
    <div className="section">
      <h2><span className="section-icon">{icon}</span> {title}</h2>
      {!items || items.length === 0 ? (
        <p className="empty">暂无数据</p>
      ) : (
        <ul className="insight-list">
          {items.map((item, i) => <li key={i}>{item}</li>)}
        </ul>
      )}
    </div>
  )
}
