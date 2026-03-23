import { DimensionScore } from '../types'

interface Props {
  dimensions: Record<string, DimensionScore> | undefined
}

const dimensionConfig = [
  { name: '体验完整性', color: '#6c5ce7' },
  { name: '用户视角还原度', color: '#00cec9' },
  { name: '分析深度', color: '#fdcb6e' },
  { name: '建议价值', color: '#ff7675' },
  { name: '表达质量', color: '#74b9ff' },
  { name: '态度与投入', color: '#a29bfe' },
]

export default function DimensionScores({ dimensions }: Props) {
  if (!dimensions) return <div className="section"><p className="empty">暂无数据</p></div>

  return (
    <div className="section">
      <h2><span className="section-icon">📊</span> 各维度得分</h2>
      <div className="dimension-grid">
        {dimensionConfig.map(({ name, color }) => {
          const d = (dimensions as Record<string, DimensionScore>)[name]
          if (!d) return null
          const pct = (d.分数 / d.满分) * 100
          return (
            <div key={name} className="dimension-card">
              <div className="dim-name">{name}</div>
              <div className="dim-score" style={{ color }}>
                {d.分数} <span>/ {d.满分}</span>
              </div>
              <div className="dim-bar">
                <div className="dim-bar-fill" style={{ width: `${pct}%`, background: color }} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
