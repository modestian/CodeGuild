import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './lib/monaco' // 本地化 Monaco（无 CDN 依赖）+ diff 语言与主题
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
