import { useState } from 'react'
import { JudgeResult } from '../types'

interface Props {
  judges: JudgeResult[]
}

const dimensionNames = [
  '体验完整性', '用户视角还原度', '分析深度',
  '建议价值', '表达质量', '态度与投入',
]

const gradeColors: Record<string, string> = {
  S: '#ff6b6b', A: '#ffa502', B: '#7bed9f', C: '#70a1ff', D: '#a29bfe',
}

export default function JudgeDetails({ judges }: Props) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})

  if (!judges || judges.length === 0) {
    return <div className="section"><h2><span className="section-icon">🧑‍⚖️</span> 评委详情</h2><p className="empty">暂无数据</p></div>
  }

  const toggle = (i: number) => setExpanded(prev => ({ ...prev, [i]: !prev[i] }))

  return (
    <div className="section" style={{ marginTop: 0 }}>
      <h2><span className="section-icon">🧑‍⚖️</span> 评委详情</h2>
      <div className="judge-grid">
        {judges.map((j, i) => {
          const gc = gradeColors[j.等级] || '#a29bfe'
          return (
            <div key={i} className="judge-card">
              <div className="judge-header" onClick={() => toggle(i)}>
                <span className="judge-name">{j.judge}</span>
                <span className="judge-score">{j.总分}分</span>
                <span className="judge-grade-tag" style={{ background: gc }}>{j.等级}</span>
                <span className={`judge-toggle ${expanded[i] ? 'open' : ''}`}>▶</span>
              </div>
              {expanded[i] && (
                <div className="judge-body">
                  {j.各维度评分 && dimensionNames.map(name => {
                    const d = (j.各维度评分 as Record<string, { 分数: number; 满分: number; 评价: string }>)[name]
                    if (!d) return null
                    return (
                      <div key={name} className="judge-dimension">
                        <div className="judge-dim-header">
                          <span>{name}</span>
                          <span className="dim-score-text">{d.分数}/{d.满分}</span>
                        </div>
                        <p className="judge-dim-comment">{d.评价}</p>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
