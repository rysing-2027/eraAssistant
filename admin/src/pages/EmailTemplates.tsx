import { useEffect, useState } from 'react'
import { Table, Card, Button, Modal, Form, Input, Switch, Space, message, Popconfirm } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { emailTemplateApi } from '../api/client'

interface Item {
  id: number
  name: string
  content: string
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export default function EmailTemplates() {
  const [loading, setLoading] = useState(true)
  const [items, setItems] = useState<Item[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editingItem, setEditingItem] = useState<Item | null>(null)
  const [form] = Form.useForm()

  const fetchItems = async () => {
    setLoading(true)
    try {
      const res = await emailTemplateApi.list()
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
    form.setFieldsValue({ is_active: true })
    setModalOpen(true)
  }

  const handleEdit = (item: Item) => {
    setEditingItem(item)
    form.setFieldsValue(item)
    setModalOpen(true)
  }

  const handleDelete = async (id: number) => {
    try {
      await emailTemplateApi.delete(id)
      message.success('删除成功')
      fetchItems()
    } catch {
      message.error('删除失败')
    }
  }

  const handleSubmit = async (values: any) => {
    try {
      if (editingItem) {
        await emailTemplateApi.update(editingItem.id, values)
        message.success('更新成功')
      } else {
        await emailTemplateApi.create(values)
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
    { title: '模板名称', dataIndex: 'name', width: 150 },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    {
      title: '内容预览',
      dataIndex: 'content',
      ellipsis: true,
      render: (text: string) => text?.substring(0, 100) + (text?.length > 100 ? '...' : '')
    },
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
        title="邮件模板"
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
        title={editingItem ? '编辑模板' : '新增模板'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => form.submit()}
        width={800}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item name="name" label="模板名称" rules={[{ required: true }]}>
            <Input placeholder="如：default、quarterly_review" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input placeholder="可选的描述说明" />
          </Form.Item>
          <Form.Item
            name="content"
            label="模板内容"
            rules={[{ required: true }]}
            extra="支持 Markdown 格式。可用占位符：{员工名}、{总分}、{等级}、{各维度评分}、{报告亮点}、{产品痛点总结}、{期望功能总结}"
          >
            <Input.TextArea
              rows={12}
              placeholder={`{员工名}你好！

感谢你提交这份产品体验报告！你的反馈对产品改进非常有价值。

---

### 📊 评分结果

**{总分}分 / {等级}级**

### ✨ 报告亮点

（汇总评委认可的报告亮点）

### 🔧 产品痛点反馈

（汇总你发现的产品问题）

### 💡 期望功能建议

（汇总你提出的改进建议）

---

期待你继续关注产品体验，为公司带来更多有价值的洞察！

Best regards,
产品体验评估委员会`}
            />
          </Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}