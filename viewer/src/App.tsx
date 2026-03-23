import { useEffect, useState } from 'react'
import { ReportData } from './types'
import { extractViewToken, fetchReportData } from './api'
import ReportHeader from './components/ReportHeader'
import OverallScore from './components/OverallScore'
import DimensionScores from './components/DimensionScores'
import InsightList from './components/InsightList'
import JudgeDetails from './components/JudgeDetails'
import LoadingScreen from './components/LoadingScreen'
import ErrorScreen from './components/ErrorScreen'

export default function App() {
  const [data, setData] = useState<ReportData | null>(null)
  const [error, setError] = useState<'NOT_FOUND' | 'NETWORK_ERROR' | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = extractViewToken()
    if (!token) {
      setError('NOT_FOUND')
      setLoading(false)
      return
    }
    fetchReportData(token)
      .then(setData)
      .catch(err => setError(err.message === 'NOT_FOUND' ? 'NOT_FOUND' : 'NETWORK_ERROR'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <LoadingScreen />
  if (error) return <ErrorScreen type={error} />
  if (!data) return null

  return (
    <div className="dashboard">
      <ReportHeader name={data.employee_name} docUrl={data.feishu_doc_url} />

      {/* Personalized intro */}
      {data.final_score?.个性化开场白 && (
        <div className="personalized-intro">
          <span className="intro-icon">💬</span>
          <p>{data.final_score.个性化开场白}</p>
        </div>
      )}

      {/* Judge details at top, collapsed by default */}
      <JudgeDetails judges={data.analysis_results} />

      <div className="dashboard-grid">
        {/* Left column: score + dimensions */}
        <div className="col-left">
          <OverallScore score={data.final_score?.总分 ?? 0} grade={data.final_score?.等级 ?? '-'} />
          <DimensionScores dimensions={data.final_score?.各维度平均分} />
        </div>

        {/* Right column: insights */}
        <div className="col-right">
          <InsightList title="报告亮点" icon="✨" items={data.final_score?.报告亮点} />
          <InsightList title="针对性反馈" icon="🎯" items={data.final_score?.针对性反馈} />
        </div>
      </div>

      {/* Pain points + Feature requests side by side */}
      <div className="insights-row">
        <InsightList title="产品痛点总结" icon="🔥" items={data.final_score?.产品痛点总结} />
        <InsightList title="期望功能总结" icon="💡" items={data.final_score?.期望功能总结} />
      </div>

      <footer className="report-footer">
        Powered by ERA · AI 产品体验评估系统
      </footer>
    </div>
  )
}
