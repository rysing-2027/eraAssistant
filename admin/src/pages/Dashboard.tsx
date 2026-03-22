import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Spin } from 'antd'
import {
  FileTextOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined
} from '@ant-design/icons'
import { recordsApi } from '../api/client'

interface Stats {
  total: number
  Submitted?: number
  Processing?: number
  'Ready for Analysis'?: number
  Analyzing?: number
  Scored?: number
  Emailing?: number
  Done?: number
  Failed?: number
}

export default function Dashboard() {
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState<Stats>({ total: 0 })

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await recordsApi.stats()
        setStats(res.data)
      } finally {
        setLoading(false)
      }
    }
    fetchStats()
  }, [])

  if (loading) {
    return <Spin />
  }

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>系统概览</h2>

      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="总记录数"
              value={stats.total}
              prefix={<FileTextOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="已完成"
              value={stats.Done || 0}
              valueStyle={{ color: '#3f8600' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="处理中"
              value={(stats.Processing || 0) + (stats.Analyzing || 0) + (stats.Emailing || 0)}
              valueStyle={{ color: '#1890ff' }}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="失败"
              value={stats.Failed || 0}
              valueStyle={{ color: '#cf1322' }}
              prefix={<CloseCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card style={{ marginTop: 24 }} title="状态分布">
        <Row gutter={[16, 16]}>
          {Object.entries(stats)
            .filter(([key]) => key !== 'total')
            .map(([key, value]) => (
              <Col xs={24} sm={12} md={8} lg={6} key={key}>
                <Statistic title={key} value={value || 0} />
              </Col>
            ))}
        </Row>
      </Card>
    </div>
  )
}