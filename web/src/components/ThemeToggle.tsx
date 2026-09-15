/** 亮/暗主题切换按钮：显示"点击后将切换到的模式"图标（月亮=切暗色，太阳=切亮色）。 */
import { toggleTheme, useThemeMode } from '../lib/theme'

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2.5M12 19.5V22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M2 12h2.5M19.5 12H22M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.6 6.6 0 0 0 9.8 9.8Z" />
    </svg>
  )
}

export function ThemeToggle() {
  const dark = useThemeMode() === 'dark'
  return (
    <button
      onClick={toggleTheme}
      title={dark ? '切换到白天模式' : '切换到黑夜模式'}
      aria-label="切换主题"
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-slate-800 text-slate-400 transition-colors hover:border-slate-700 hover:text-slate-200"
    >
      {dark ? <SunIcon /> : <MoonIcon />}
    </button>
  )
}
