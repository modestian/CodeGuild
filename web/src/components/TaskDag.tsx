/** Task DAG 视图（React Flow）：任务依赖图 + 状态着色。
 * 节点保持紧凑（ID + 标题 + 状态 + 重试），完整信息在点击后的 Task Detail 抽屉中展示。
 */
import { useMemo } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import type { TaskItem } from '../api/types'
import { useThemeMode } from '../lib/theme'
import { taskStatusMeta } from './badges'

interface TaskNodeData extends Record<string, unknown> {
  id: string
  title: string
  status: string
  attempts: number
}

function TaskNode({ data }: NodeProps) {
  const d = data as unknown as TaskNodeData
  const meta = taskStatusMeta(d.status)
  return (
    <div
      className={`w-[200px] cursor-pointer rounded-md border bg-slate-900 px-2.5 py-2 transition-colors hover:border-slate-500/70 ${meta.border} ${meta.ring}`}
    >
      <div className="flex items-center gap-2">
        <span className="shrink-0 font-mono text-[11px] font-semibold text-slate-400">{d.id}</span>
        <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-slate-200" title={d.title}>
          {d.title}
        </span>
      </div>
      <div className="mt-1.5 flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${meta.dot}`} />
        <span className={`text-[10px] font-medium ${meta.text}`}>{meta.label}</span>
        {d.attempts > 1 && (
          <span className="ml-auto font-mono text-[10px] text-slate-500">尝试 {d.attempts} 次</span>
        )}
      </div>
      <Handle type="target" position={Position.Top} className="!h-1.5 !w-1.5 !border-slate-600 !bg-slate-600" />
      <Handle type="source" position={Position.Bottom} className="!h-1.5 !w-1.5 !border-slate-600 !bg-slate-600" />
    </div>
  )
}

const nodeTypes = { task: TaskNode }

/** 按依赖分层布局（纵向：依赖在上、后继在下）：level = 最长依赖链深度；同层按出现顺序横向排布。 */
function layout(tasks: TaskItem[]): { nodes: Node[]; edges: Edge[] } {
  const byId = new Map(tasks.map((t) => [t.id, t]))
  const levelCache = new Map<string, number>()
  const levelOf = (id: string, guard = new Set<string>()): number => {
    if (levelCache.has(id)) return levelCache.get(id)!
    if (guard.has(id)) return 0 // 环保护（上游已校验 DAG，此处仅防御）
    guard.add(id)
    const t = byId.get(id)
    const deps = (t?.dependencies ?? []).filter((d) => byId.has(d))
    const lv = deps.length ? Math.max(...deps.map((d) => levelOf(d, guard))) + 1 : 0
    levelCache.set(id, lv)
    return lv
  }

  const groups = new Map<number, TaskItem[]>()
  for (const t of tasks) {
    const lv = levelOf(t.id)
    if (!groups.has(lv)) groups.set(lv, [])
    groups.get(lv)!.push(t)
  }

  const nodes: Node[] = []
  for (const [lv, items] of groups) {
    items.forEach((t, i) => {
      nodes.push({
        id: t.id,
        type: 'task',
        position: { x: 24 + i * 230, y: 24 + lv * 104 },
        data: {
          id: t.id,
          title: t.title,
          status: t.status,
          attempts: t.attempts,
        } satisfies TaskNodeData,
        draggable: false,
      })
    })
  }

  const edges: Edge[] = []
  for (const t of tasks) {
    for (const dep of t.dependencies ?? []) {
      if (!byId.has(dep)) continue
      edges.push({
        id: `e-${dep}-${t.id}`,
        source: dep,
        target: t.id,
        type: 'smoothstep',
        animated: t.status === 'RUNNING',
      })
    }
  }
  return { nodes, edges }
}

export function TaskDag({ tasks, onSelect }: { tasks: TaskItem[]; onSelect?: (taskId: string) => void }) {
  const dark = useThemeMode() === 'dark'
  const { nodes, edges } = useMemo(() => layout(tasks), [tasks])

  if (!tasks.length) {
    return (
      <div className="flex h-full items-center justify-center px-4 text-center text-sm text-slate-500">
        任务尚未生成（等待 Architect 产出 Task DAG）
      </div>
    )
  }

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.3}
        maxZoom={1.6}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        onNodeClick={(_, node) => onSelect?.(node.id)}
        proOptions={{ hideAttribution: false }}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color={dark ? '#1e293b' : '#cbd5e1'} />
        <Controls showInteractive={false} position="bottom-left" />
      </ReactFlow>
    </div>
  )
}
