import { useEffect, useState } from 'react'
import { Table, Card, Tag, Select, Button, Modal, Descriptions, Collapse, Typography } from 'antd'
import { EyeOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { recordsApi } from '../api/client'

const { Panel } = Collapse
const { Text } = Typography

interface RecordItem {
  id: number
  feishu_record_id: string
  employee_name: string
  employee_email: string
  status: string
  file_name: string
  final_score: any
  error_message: string | null
  retry_count: number
  created_at: string
  updated_at: string
  email_sent_at: string | null
  raw_text?: string
  analysis_results?: any[]
  email_content?: string
}

const statusColors: Record<string, string> = {
  'Submitted': 'blue',
  'Processing': 'orange',
  'Ready for Analysis': 'cyan',
  'Analyzing': 'purple',
  'Scored': 'geekblue',
  'Emailing': 'processing',
  'Done': 'success',
  'Failed': 'error'
}

export default function Records() {
  const [loading, setLoading] = useState(true)
  const [records, setRecords] = useState<RecordItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [detailModal, setDetailModal] = useState<RecordItem | null>(null)

  const fetchRecords = async () => {
    setLoading(true)
    try {
      const res = await recordsApi.list({
        page,
        page_size: 10,
        status: statusFilter
      })
      setRecords(res.data.records)
      setTotal(res.data.total)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchRecords()
  }, [page, statusFilter])

  const showDetail = async (id: number) => {
    try {
      const res = await recordsApi.get(id)
      setDetailModal(res.data)
    } catch {}
  }

  const renderJudgeResult = (judge: any, index: number) => {
    if (!judge) return null

    const judgeName = judge.judge || `评委 ${index + 1}`

    return (
      <Panel
        header={
          <span>
            <Tag color="blue">{judgeName}</Tag>
            {judge.总分 && <span>总分: {judge.总分}分 / {judge.等级}</span>}
            {judge.error && <span style={{ color: 'red' }}> - 错误</span>}
          </span>
        }
        key={index}
      >
        {judge.error ? (
          <Text type="danger">{judge.error}</Text>
        ) : (
          <Descriptions bordered size="small" column={1}>
            {judge.总分 && (
              <Descriptions.Item label="总分">
                <strong>{judge.总分}分 / {judge.等级}级</strong>
              </Descriptions.Item>
            )}
            {judge.各维度评分 && (
              <Descriptions.Item label="各维度评分">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '8px' }}>
                  {Object.entries(judge.各维度评分).map(([key, value]: [string, any]) => (
                    <div key={key}>
                      <Text strong>{key}</Text>: {value.分数}/{value.满分}
                      {value.评价 && <div><Text type="secondary" style={{ fontSize: 12 }}>{value.评价}</Text></div>}
                    </div>
                  ))}
                </div>
              </Descriptions.Item>
            )}
            {judge.报告亮点 && judge.报告亮点.length > 0 && (
              <Descriptions.Item label="报告亮点">
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {judge.报告亮点.map((item: string, i: number) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </Descriptions.Item>
            )}
            {judge.产品痛点总结 && judge.产品痛点总结.length > 0 && (
              <Descriptions.Item label="产品痛点">
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {judge.产品痛点总结.map((item: string, i: number) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </Descriptions.Item>
            )}
            {judge.期望功能总结 && judge.期望功能总结.length > 0 && (
              <Descriptions.Item label="期望功能">
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {judge.期望功能总结.map((item: string, i: number) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Panel>
    )
  }

  const columns: ColumnsType<RecordItem> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '员工姓名', dataIndex: 'employee_name', width: 100 },
    { title: '员工邮箱', dataIndex: 'employee_email', width: 200 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 140,
      render: (status: string) => (
        <Tag color={statusColors[status] || 'default'}>{status}</Tag>
      )
    },
    { title: '文件名', dataIndex: 'file_name', ellipsis: true },
    {
      title: '最终得分',
      dataIndex: 'final_score',
      width: 80,
      render: (score: any) => score?.总分 ? `${score.总分}分` : '-'
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (date: string) => date ? new Date(date).toLocaleString() : '-'
    },
    {
      title: '操作',
      width: 80,
      render: (_, record) => (
        <Button icon={<EyeOutlined />} onClick={() => showDetail(record.id)} />
      )
    }
  ]

  return (
    <div>
      <Card
        title="报告记录"
        extra={
          <Select
            allowClear
            placeholder="筛选状态"
            style={{ width: 160 }}
            value={statusFilter}
            onChange={setStatusFilter}
          >
            {Object.keys(statusColors).map(status => (
              <Select.Option key={status} value={status}>{status}</Select.Option>
            ))}
          </Select>
        }
      >
        <Table
          loading={loading}
          columns={columns}
          dataSource={records}
          rowKey="id"
          pagination={{
            current: page,
            total,
            pageSize: 10,
            onChange: setPage
          }}
        />
      </Card>

      <Modal
        title="记录详情"
        open={!!detailModal}
        onCancel={() => setDetailModal(null)}
        footer={null}
        width={900}
      >
        {detailModal && (
          <div>
            <Descriptions bordered column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="ID">{detailModal.id}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={statusColors[detailModal.status] || 'default'}>
                  {detailModal.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="员工姓名">{detailModal.employee_name}</Descriptions.Item>
              <Descriptions.Item label="员工邮箱">{detailModal.employee_email}</Descriptions.Item>
              <Descriptions.Item label="文件名" span={2}>{detailModal.file_name}</Descriptions.Item>
              <Descriptions.Item label="重试次数">{detailModal.retry_count}</Descriptions.Item>
              <Descriptions.Item label="邮件发送">
                {detailModal.email_sent_at ? new Date(detailModal.email_sent_at).toLocaleString() : '未发送'}
              </Descriptions.Item>
            </Descriptions>

            {detailModal.analysis_results && detailModal.analysis_results.length > 0 && (
              <Card title="评委评分详情" style={{ marginBottom: 16 }} size="small">
                <Collapse bordered={false}>
                  {detailModal.analysis_results.map((judge, index) => renderJudgeResult(judge, index))}
                </Collapse>
              </Card>
            )}

            {detailModal.final_score && (
              <Card title="最终评分" style={{ marginBottom: 16 }} size="small">
                <Descriptions bordered size="small" column={2}>
                  <Descriptions.Item label="总分">
                    <strong style={{ fontSize: 18 }}>{detailModal.final_score.总分}分 / {detailModal.final_score.等级}级</strong>
                  </Descriptions.Item>
                  {detailModal.final_score.各维度平均分 && (
                    <Descriptions.Item label="各维度平均分" span={2}>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
                        {Object.entries(detailModal.final_score.各维度平均分).map(([key, value]: [string, any]) => (
                          <div key={key}>
                            <Text strong>{key}</Text>: {value.分数}/{value.满分}
                          </div>
                        ))}
                      </div>
                    </Descriptions.Item>
                  )}
                  {detailModal.final_score.报告亮点 && (
                    <Descriptions.Item label="报告亮点" span={2}>
                      <ul style={{ margin: 0, paddingLeft: 20 }}>
                        {detailModal.final_score.报告亮点.map((item: string, i: number) => (
                          <li key={i}>{item}</li>
                        ))}
                      </ul>
                    </Descriptions.Item>
                  )}
                  {detailModal.final_score.产品痛点总结 && (
                    <Descriptions.Item label="产品痛点" span={2}>
                      <ul style={{ margin: 0, paddingLeft: 20 }}>
                        {detailModal.final_score.产品痛点总结.map((item: string, i: number) => (
                          <li key={i}>{item}</li>
                        ))}
                      </ul>
                    </Descriptions.Item>
                  )}
                  {detailModal.final_score.期望功能总结 && (
                    <Descriptions.Item label="期望功能" span={2}>
                      <ul style={{ margin: 0, paddingLeft: 20 }}>
                        {detailModal.final_score.期望功能总结.map((item: string, i: number) => (
                          <li key={i}>{item}</li>
                        ))}
                      </ul>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </Card>
            )}

            {detailModal.error_message && (
              <Card title="错误信息" style={{ marginBottom: 16 }} size="small">
                <Text type="danger">{detailModal.error_message}</Text>
              </Card>
            )}

            {detailModal.email_content && (
              <Card title="邮件内容" size="small">
                <pre style={{ margin: 0, maxHeight: 400, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                  {detailModal.email_content}
                </pre>
              </Card>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}