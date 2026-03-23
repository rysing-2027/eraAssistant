interface Props {
  score: number
  grade: string
}

const gradeConfig: Record<string, { color: string; gradient: string }> = {
  S: { color: '#ff6b6b', gradient: 'url(#grad-s)' },
  A: { color: '#ffa502', gradient: 'url(#grad-a)' },
  B: { color: '#7bed9f', gradient: 'url(#grad-b)' },
  C: { color: '#70a1ff', gradient: 'url(#grad-c)' },
  D: { color: '#a29bfe', gradient: 'url(#grad-d)' },
}

export default function OverallScore({ score, grade }: Props) {
  const config = gradeConfig[grade] || { color: '#a29bfe', gradient: '' }
  const radius = 65
  const circumference = 2 * Math.PI * radius
  const pct = Math.min(score / 100, 1)
  const offset = circumference * (1 - pct)

  return (
    <div className="overall-score">
      <div className="score-ring">
        <svg viewBox="0 0 160 160">
          <defs>
            <linearGradient id="grad-s" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#ff6b6b" />
              <stop offset="100%" stopColor="#ee5a24" />
            </linearGradient>
            <linearGradient id="grad-a" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#ffa502" />
              <stop offset="100%" stopColor="#ff6348" />
            </linearGradient>
            <linearGradient id="grad-b" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#7bed9f" />
              <stop offset="100%" stopColor="#2ed573" />
            </linearGradient>
            <linearGradient id="grad-c" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#70a1ff" />
              <stop offset="100%" stopColor="#1e90ff" />
            </linearGradient>
            <linearGradient id="grad-d" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#a29bfe" />
              <stop offset="100%" stopColor="#6c5ce7" />
            </linearGradient>
          </defs>
          <circle className="ring-bg" cx="80" cy="80" r={radius} />
          <circle
            className="ring-fill"
            cx="80" cy="80" r={radius}
            stroke={config.gradient || config.color}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
          />
        </svg>
        <div className="score-inner">
          <div className="score-number" style={{ color: config.color }}>{score}</div>
          <div className="score-total">/ 100</div>
        </div>
      </div>
      <div>
        <div className="score-grade-badge" style={{ background: config.color }}>{grade} 级</div>
      </div>
      <div className="score-label">综合评分</div>
    </div>
  )
}
