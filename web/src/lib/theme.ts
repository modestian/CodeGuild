/** 主题状态（亮/暗）：localStorage 持久化 + html.dark 类切换。
 * 初始值优先读取 localStorage（index.html 内联脚本已提前应用，避免首屏闪烁），
 * 无记录时跟随系统偏好；通过 useSyncExternalStore 让所有订阅组件同步。
 */
import { useSyncExternalStore } from 'react'

export type ThemeMode = 'light' | 'dark'

const STORAGE_KEY = 'copilot-theme'
const listeners = new Set<() => void>()

function readInitial(): ThemeMode {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    /* 隐私模式等场景忽略存储失败 */
  }
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}

let current: ThemeMode = readInitial()

function applyClass(mode: ThemeMode) {
  document.documentElement.classList.toggle('dark', mode === 'dark')
}

// 模块加载时同步一次（与 index.html 内联脚本保持一致）
applyClass(current)

export function setTheme(mode: ThemeMode) {
  current = mode
  try {
    localStorage.setItem(STORAGE_KEY, mode)
  } catch {
    /* ignore */
  }
  applyClass(mode)
  listeners.forEach((l) => l())
}

export function toggleTheme() {
  setTheme(current === 'dark' ? 'light' : 'dark')
}

/** 订阅当前主题；组件在主题切换时自动重渲染（用于 Monaco / 图表等 JS 侧配色）。 */
export function useThemeMode(): ThemeMode {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => current,
  )
}
