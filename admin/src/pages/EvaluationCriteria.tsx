import { useEffect, useState } from 'react'
import { Table, Card, Button, Modal, Form, Input, Switch, InputNumber, Space, message, Popconfirm } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { evaluationCriteriaApi } from '../api/client'

interface Item {
  id: number
  section_name: string
  content: string
  description: string | null
  sort_order: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export default function EvaluationCriteria() {
  const [loading, setLoading] = useState(true)
  const [items, setItems] = useState<Item[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<Item | null>(null)
  const [form] = Form.useForm()

  const fetchItems = async () => {
    setLoading(true)
    try {
      const res = await evaluationCriteriaApi.list()
      setItems(res.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchItems()
  }, [])

  const handleCreate = () => {
    setEditingItem(null)
    form.resetFields()
    form.setFieldsValue({ is_active: true, sort_order: 0 })
    setModalOpen(true)
  }

  const handleEdit = (item: Item) => {
    setEditingItem(item)
    form.setFieldsValue(item)
    setModalOpen(true)
  }

  const handleDelete = async (id: number) => {
    try {
      await evaluationCriteriaApi.delete(id)
      message.success('删除成功')
      fetchItems()
    } catch {
      message.error('删除失败')
    }
  }

  const handleSubmit = async (values: any) => {
    try {
      if (editingItem) {
        await evaluationCriteriaApi.update(editingItem.id, values)
        message.success('更新成功')
      } else {
        await evaluationCriteriaApi.create(values)
        message.success('创建成功')
      }
      setModalOpen(false)
      fetchItems()
    } catch {
      message.error('操作失败')
    }
  }

  const columns: ColumnsType<Item> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '章节名称', dataIndex: 'section_name', width: 150 },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    {
      title: '内容',
      dataIndex: 'content',
      ellipsis: true,
      render: (text: string) => text?.substring(0, 100) + (text?.length > 100 ? '...' : '')
    },
    { title: '排序', dataIndex: 'sort_order', width: 80 },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      render: (active: boolean) => active ? '启用' : '禁用'
    },
    {
      title: '操作',
      width: 120,
      render: (_, record) => (
        <Space>
          <Button icon={<EditOutlined />} onClick={() => handleEdit(record)} />
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(record.id)}>
            <Button icon={<DeleteOutlined />} danger />
          </Popconfirm>
        </Space>
      )
    }
  ]

  return (
    <div>
      <Card
        title="评估标准"
        extra={<Button icon={<PlusOutlined />} onClick={handleCreate}>新增</Button>}
      >
        <Table
          loading={loading}
          columns={columns}
          dataSource={items}
          rowKey="id"
        />
      </Card>

      <Modal
        title={editingItem ? '编辑标准' : '新增标准'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        width={700}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item name="section_name" label="章节名称" rules={[{ required: true }]}>
            <Input placeholder="如：评分等级、评分维度" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="可选的描述说明" />
          </Form.Item>
          <Form.Item name="content" label="内容" rules={[{ required: true }]}>
            <Input.TextArea rows={8} placeholder="详细评估标准内容..." />
          </Form.Item>
          <Form.Item name="sort_order" label="排序">
            <InputNumber min={0} />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}