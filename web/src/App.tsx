/** 应用路由：项目工作台（/）与运行详情（/runs/:runId）。 */
import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { ProjectsPage } from './pages/ProjectsPage'
import { RunPage } from './pages/RunPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/run/:runId" element={<RunPage />} />
      </Routes>
    </BrowserRouter>
  )
}
