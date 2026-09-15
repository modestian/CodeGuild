/** Monaco 本地化配置：使用 npm 包（无 CDN 依赖）+ 注册 unified-diff 语言与深色主题。 */
import * as monaco from 'monaco-editor/editor/editor.api'
import editorWorker from 'monaco-editor/editor/editor.worker?worker'
import { loader } from '@monaco-editor/react'

// 本地 worker（Vite ?worker 打包）
self.MonacoEnvironment = {
  getWorker: () => new editorWorker(),
}

// 使用本地安装的 monaco（@monaco-editor/react 默认从 CDN 加载）
loader.config({ monaco: monaco as unknown as typeof import('monaco-editor') })

// ---------- unified diff 语言（Monarch 分词） ----------
monaco.languages.register({ id: 'unified-diff' })
monaco.languages.setMonarchTokensProvider('unified-diff', {
  tokenizer: {
    root: [
      [/^diff --git .*/, 'keyword'],
      [/^index .*/, 'comment'],
      [/^(new file mode|deleted file mode|old mode|new mode|similarity index|rename from|rename to|copy from|copy to) .*/, 'comment'],
      [/^--- .*/, 'string'],
      [/^\+\+\+ .*/, 'string'],
      [/^@@.*/, 'type'],
      [/^\+.*/, 'inserted'],
      [/^-.*/, 'deleted'],
    ],
  },
})

// ---------- 深色主题 ----------
monaco.editor.defineTheme('copilot-dark', {
  base: 'vs-dark',
  inherit: true,
  rules: [
    { token: 'keyword', foreground: '93c5fd' },
    { token: 'comment', foreground: '64748b' },
    { token: 'type', foreground: '60a5fa' },
    { token: 'string', foreground: '94a3b8' },
    { token: 'inserted', foreground: '86efac' },
    { token: 'deleted', foreground: 'fda4af' },
  ],
  colors: {
    'editor.background': '#0b1220',
    'editor.lineHighlightBackground': '#0b1220',
    'editorLineNumber.foreground': '#475569',
    'editorLineNumber.activeForeground': '#94a3b8',
    'editorGutter.background': '#0b1220',
    'editor.selectionBackground': '#33415588',
  },
})

// ---------- 亮色主题 ----------
monaco.editor.defineTheme('copilot-light', {
  base: 'vs',
  inherit: true,
  rules: [
    { token: 'keyword', foreground: '1d4ed8' },
    { token: 'comment', foreground: '64748b' },
    { token: 'type', foreground: '2563eb' },
    { token: 'string', foreground: '475569' },
    { token: 'inserted', foreground: '15803d' },
    { token: 'deleted', foreground: 'be123c' },
  ],
  colors: {
    'editor.background': '#ffffff',
    'editor.lineHighlightBackground': '#ffffff',
    'editorLineNumber.foreground': '#94a3b8',
    'editorLineNumber.activeForeground': '#475569',
    'editorGutter.background': '#ffffff',
    'editor.selectionBackground': '#bfdbfe88',
  },
})

export { monaco }
