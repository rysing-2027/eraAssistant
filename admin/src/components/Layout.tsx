import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout as AntLayout, Menu, Dropdown, Avatar } from 'antd'
import {
  DashboardOutlined,
  FileTextOutlined,
  BookOutlined,
  CheckSquareOutlined,
  MailOutlined,
  LogoutOutlined,
  UserOutlined
} from '@ant-design/icons'
import { authApi } from '../api/client'

const { Header, Sider, Content } = AntLayout

interface LayoutProps {
  onLogout: () => void
}

export default function Layout({ onLogout }: LayoutProps) {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  const menuItems = [
    { key: '/', icon: <DashboardOutlined />, label: '概览' },
    { key: '/records', icon: <FileTextOutlined />, label: '报告记录' },
    { key: '/product-knowledge', icon: <BookOutlined />, label: '产品知识库' },
    { key: '/evaluation-criteria', icon: <CheckSquareOutlined />, label: '评估标准' },
    { key: '/email-templates', icon: <MailOutlined />, label: '邮件模板' }
  ]

  const handleLogout = async () => {
    try {
      await authApi.logout()
    } catch {}
    onLogout()
  }

  const userMenu = {
    items: [
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        onClick: handleLogout
      }
    ]
  }

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}>
        <div style={{
          height: 32,
          margin: 16,
          background: 'rgba(255, 255, 255, 0.2)',
          borderRadius: 6,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontWeight: 'bold'
        }}>
          {collapsed ? 'ERA' : 'ERA Admin'}
        </div>
        <Menu
          theme="dark"
          selectedKeys={[location.pathname]}
          mode="inline"
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <AntLayout>
        <Header style={{
          padding: '0 24px',
          background: '#fff',
          display: 'flex',
          justifyContent: 'flex-end',
          alignItems: 'center'
        }}>
          <Dropdown menu={userMenu}>
            <Avatar style={{ cursor: 'pointer' }} icon={<UserOutlined />} />
          </Dropdown>
        </Header>
        <Content style={{ margin: '24px 16px', padding: 24, background: '#fff', borderRadius: 8, minHeight: 280 }}>
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  )
}