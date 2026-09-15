/** Diff 查看器（Monaco）：unified diff 解析 + 文件切换 + 行级着色。 */
import { useMemo, useRef, useState } from 'react'
import Editor, { type OnMount } from '@monaco-editor/react'
import type { editor as MonacoEditorNs } from 'monaco-editor'

import { monaco } from '../lib/monaco'
import { useThemeMode } from '../lib/theme'

export interface DiffFile {
  path: string
  text: string
  additions: number
  deletions: number
  isNew: boolean
  isDeleted: boolean
}

export function parseUnifiedDiff(raw: string): DiffFile[] {
  const files: DiffFile[] = []
  let cur: DiffFile | null = null
  for (const line of raw.split('\n')) {
    if (line.startsWith('diff --git ')) {
      const m = line.match(/^diff --git a\/(.+) b\/(.+)$/)
      cur = {
        path: m ? m[2] : line.slice('diff --git '.length),
        text: '',
        additions: 0,
        deletions: 0,
        isNew: false,
        isDeleted: false,
      }
      files.push(cur)
      continue
    }
    if (!cur) continue
    cur.text += line + '\n'
    if (line.startsWith('new file mode')) cur.isNew = true
    else if (line.startsWith('deleted file mode')) cur.isDeleted = true
    else if (line.startsWith('+') && !line.startsWith('+++')) cur.additions += 1
    else if (line.startsWith('-') && !line.startsWith('---')) cur.deletions += 1
  }
  return files
}

const EDITOR_OPTIONS: MonacoEditorNs.IStandaloneEditorConstructionOptions = {
  readOnly: true,
  minimap: { enabled: false },
  fontFamily: '"Cascadia Code", "JetBrains Mono", Consolas, monospace',
  fontSize: 12,
  lineHeight: 19,
  renderLineHighlight: 'none',
  scrollBeyondLastLine: false,
  folding: false,
  glyphMargin: false,
  lineDecorationsWidth: 10,
  lineNumbersMinChars: 3,
  wordWrap: 'off',
  scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8 },
  overviewRulerLanes: 0,
  stickyScroll: { enabled: false },
  contextmenu: false,
}

export function DiffViewer({ diff, loading }: { diff: string; loading?: boolean }) {
  const dark = useThemeMode() === 'dark'
  const files = useMemo(() => parseUnifiedDiff(diff), [diff])
  const [selected, setSelected] = useState<string | null>(null)
  const editorRef = useRef<MonacoEditorNs.IStandaloneCodeEditor | null>(null)
  const decoRef = useRef<MonacoEditorNs.IEditorDecorationsCollection | null>(null)

  const active = files.find((f) => f.path === selected) ?? files[0] ?? null

  const applyDecorations = (editor: MonacoEditorNs.IStandaloneCodeEditor) => {
    const model = editor.getModel()
    if (!model || !decoRef.current) return
    const decos: MonacoEditorNs.IModelDeltaDecoration[] = []
    for (let i = 1; i <= model.getLineCount(); i += 1) {
      const line = model.getLineContent(i)
      let cls = ''
      if (line.startsWith('@@')) cls = 'diff-line-hunk'
      else if (line.startsWith('+') && !line.startsWith('+++')) cls = 'diff-line-added'
      else if (line.startsWith('-') && !line.startsWith('---')) cls = 'diff-line-removed'
      if (cls) {
        decos.push({ range: new monaco.Range(i, 1, i, 1), options: { isWholeLine: true, className: cls } })
      }
    }
    decoRef.current.set(decos)
  }

  const onMount: OnMount = (editor) => {
    editorRef.current = editor
    decoRef.current = editor.createDecorationsCollection([])
    applyDecorations(editor)
    editor.onDidChangeModelContent(() => applyDecorations(editor))
  }

  const totalAdd = files.reduce((s, f) => s + f.additions, 0)
  const totalDel = files.reduce((s, f) => s + f.deletions, 0)

  if (!active) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-500">
        {loading ? '加载 diff…' : '暂无代码变更（工作区与基线一致）'}
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-slate-800/60 px-3 py-1.5 text-[11px] text-slate-500">
        <span>{files.length} 个文件</span>
        <span className="font-mono text-emerald-400">+{totalAdd}</span>
        <span className="font-mono text-rose-400">-{totalDel}</span>
      </div>
      <div className="flex min-h-0 flex-1">
        {/* 文件列表 */}
        <div className="w-44 shrink-0 overflow-y-auto border-r border-slate-800/60 py-1">
          {files.map((f) => (
            <button
              key={f.path}
              onClick={() => setSelected(f.path)}
              className={`block w-full truncate px-2.5 py-1.5 text-left font-mono text-[11px] leading-4 transition-colors ${
                f.path === active.path
                  ? 'bg-slate-800 text-slate-100'
                  : 'text-slate-400 hover:bg-slate-800/40 hover:text-slate-200'
              }`}
              title={f.path}
            >
              <span className="block truncate">{f.path}</span>
              <span className="text-[10px]">
                <span className="text-emerald-400">+{f.additions}</span>{' '}
                <span className="text-rose-400">-{f.deletions}</span>
                {f.isNew && <span className="ml-1 text-emerald-400">新增</span>}
                {f.isDeleted && <span className="ml-1 text-rose-400">删除</span>}
              </span>
            </button>
          ))}
        </div>
        {/* diff 内容 */}
        <div className="min-w-0 flex-1">
          <Editor
            height="100%"
            language="unified-diff"
            theme={dark ? 'copilot-dark' : 'copilot-light'}
            value={active.text}
            onMount={onMount}
            options={EDITOR_OPTIONS}
            loading={<div className="p-4 text-xs text-slate-500">加载编辑器…</div>}
          />
        </div>
      </div>
    </div>
  )
}

