/** 产出物结构化渲染器：需求 / 架构 / 测试 / 审查 / 最终报告（数据来自各 Agent 的 JSON 产物）。 */

// ---------- 安全取值工具 ----------
export const asObj = (v: unknown): Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : {}
export const asArr = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
export const asStr = (v: unknown): string => (typeof v === 'string' ? v : '')
export const asNum = (v: unknown): number => (typeof v === 'number' ? v : 0)

// ---------- 共享小部件 ----------
export function Pill({ children, cls = 'bg-slate-800 text-slate-300' }: { children: React.ReactNode; cls?: string }) {
  return <span className={`inline-flex shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] leading-4 ${cls}`}>{children}</span>
}

function Section({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-2 border-b border-slate-800/70 pb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
        {title}
        {count !== undefined && <span className="rounded bg-slate-800/80 px-1.5 text-[10px] font-normal text-slate-400">{count}</span>}
      </h3>
      {children}
    </section>
  )
}

function EmptySection() {
  return <div className="text-xs text-slate-600">（无内容）</div>
}

const PRIORITY_CLS: Record<string, string> = {
  high: 'bg-rose-950/80 text-rose-300',
  medium: 'bg-amber-950/80 text-amber-300',
  low: 'bg-slate-800 text-slate-400',
}

// ---------- 需求分析（Product Agent） ----------
export function RequirementsView({ data }: { data: Record<string, unknown> }) {
  const summary = asStr(data.summary)
  const features = asArr(data.features)
  const stories = asArr(data.user_stories)
  const criteria = asArr(data.acceptance_criteria)
  const nfrs = asArr(data.non_functional_requirements)
  const questions = asArr(data.open_questions)

  return (
    <div className="space-y-5">
      {summary && (
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 text-xs leading-relaxed text-slate-300">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">需求摘要</div>
          <p className="whitespace-pre-line">{summary}</p>
        </div>
      )}

      <Section title="功能点 Features" count={features.length}>
        {features.length === 0 ? (
          <EmptySection />
        ) : (
          <div className="grid gap-2 lg:grid-cols-2">
            {features.map((f, i) => {
              const o = asObj(f)
              return (
                <div key={asStr(o.id) || i} className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                  <div className="flex items-center gap-2">
                    <Pill cls="bg-slate-800 text-slate-300">{asStr(o.id)}</Pill>
                    <span className="text-xs font-semibold text-slate-200">{asStr(o.name)}</span>
                    <Pill cls={PRIORITY_CLS[asStr(o.priority)] ?? PRIORITY_CLS.low}>{asStr(o.priority)}</Pill>
                  </div>
                  <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{asStr(o.description)}</p>
                </div>
              )
            })}
          </div>
        )}
      </Section>

      <Section title="用户故事 User Stories" count={stories.length}>
        {stories.length === 0 ? (
          <EmptySection />
        ) : (
          <div className="space-y-1.5">
            {stories.map((s, i) => {
              const o = asObj(s)
              return (
                <div key={asStr(o.id) || i} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded border border-slate-800/70 bg-slate-900/40 px-2.5 py-2 text-xs">
                  <Pill cls="bg-slate-800 text-slate-300">{asStr(o.id)}</Pill>
                  <span className="text-slate-400">
                    作为 <span className="text-slate-200">{asStr(o.as_a)}</span>，我希望{' '}
                    <span className="text-slate-200">{asStr(o.i_want)}</span>，以便{' '}
                    <span className="text-slate-200">{asStr(o.so_that)}</span>
                  </span>
                  {asStr(o.feature_id) && <Pill cls="bg-slate-800 text-slate-500">{asStr(o.feature_id)}</Pill>}
                </div>
              )
            })}
          </div>
        )}
      </Section>

      <Section title="验收标准 Acceptance Criteria" count={criteria.length}>
        {criteria.length === 0 ? (
          <EmptySection />
        ) : (
          <ul className="space-y-1.5">
            {criteria.map((c, i) => {
              const o = asObj(c)
              return (
                <li key={asStr(o.id) || i} className="flex items-start gap-2 rounded border border-slate-800/70 bg-slate-900/40 px-2.5 py-2 text-xs">
                  <Pill cls="bg-slate-800 text-slate-300">{asStr(o.id)}</Pill>
                  <span className="min-w-0 flex-1 leading-relaxed text-slate-400">{asStr(o.description)}</span>
                </li>
              )
            })}
          </ul>
        )}
      </Section>

      {nfrs.length > 0 && (
        <Section title="非功能需求 NFR" count={nfrs.length}>
          <ul className="space-y-1.5">
            {nfrs.map((n, i) => {
              const o = asObj(n)
              return (
                <li key={asStr(o.id) || i} className="flex items-start gap-2 rounded border border-slate-800/70 bg-slate-900/40 px-2.5 py-2 text-xs">
                  <Pill cls="bg-slate-800 text-slate-300">{asStr(o.id)}</Pill>
                  <Pill cls="bg-slate-800 text-slate-400">{asStr(o.category)}</Pill>
                  <span className="min-w-0 flex-1 leading-relaxed text-slate-400">{asStr(o.description)}</span>
                </li>
              )
            })}
          </ul>
        </Section>
      )}

      {questions.length > 0 && (
        <Section title="待澄清问题 Open Questions" count={questions.length}>
          <ul className="space-y-1.5">
            {questions.map((q, i) => {
              const o = asObj(q)
              return (
                <li key={asStr(o.id) || i} className="rounded border border-amber-900/40 bg-amber-950/10 px-2.5 py-2 text-xs">
                  <div className="flex items-start gap-2">
                    <Pill cls="bg-amber-950 text-amber-300">{asStr(o.id)}</Pill>
                    <span className="min-w-0 flex-1 leading-relaxed text-slate-300">{asStr(o.question)}</span>
                  </div>
                  {asStr(o.assumption) && (
                    <div className="mt-1 pl-8 text-[11px] leading-relaxed text-slate-500">
                      默认假设：{asStr(o.assumption)}
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        </Section>
      )}
    </div>
  )
}

// ---------- 架构设计（Architect Agent） ----------
export function ArchitectureView({ data }: { data: Record<string, unknown> }) {
  const summary = asStr(data.summary)
  const overview = asStr(data.design_overview)
  const modules = asArr(data.modules)
  const contracts = asArr(data.api_contracts)
  const models = asArr(data.data_models)
  const deps = asArr(data.module_dependencies)
  const constraints = asArr(data.constraints)

  return (
    <div className="space-y-5">
      {summary && (
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3 text-xs leading-relaxed text-slate-300">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">架构摘要</div>
          <p className="whitespace-pre-line">{summary}</p>
        </div>
      )}
      {overview && (
        <Section title="设计概述">
          <p className="whitespace-pre-line rounded border border-slate-800/70 bg-slate-900/40 p-3 text-xs leading-relaxed text-slate-400">
            {overview}
          </p>
        </Section>
      )}

      <Section title="模块设计 Modules" count={modules.length}>
        {modules.length === 0 ? (
          <EmptySection />
        ) : (
          <div className="grid gap-2 lg:grid-cols-2">
            {modules.map((m, i) => {
              const o = asObj(m)
              const interfaces = asArr(o.interfaces).map(asStr).filter(Boolean)
              const files = asArr(o.files).map(asStr).filter(Boolean)
              return (
                <div key={asStr(o.name) || i} className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                  <div className="text-xs font-semibold text-slate-200">{asStr(o.name)}</div>
                  <p className="mt-1 text-xs leading-relaxed text-slate-400">{asStr(o.purpose)}</p>
                  {interfaces.length > 0 && (
                    <ul className="mt-2 space-y-0.5">
                      {interfaces.map((itf, j) => (
                        <li key={j} className="font-mono text-[10px] leading-4 text-slate-400">
                          ◦ {itf}
                        </li>
                      ))}
                    </ul>
                  )}
                  {files.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {files.map((f, j) => (
                        <Pill key={j} cls="bg-slate-800/80 text-slate-400">
                          {f}
                        </Pill>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </Section>

      {contracts.length > 0 && (
        <Section title="接口契约 API Contracts" count={contracts.length}>
          <div className="space-y-1.5">
            {contracts.map((c, i) => {
              const o = asObj(c)
              return (
                <div key={asStr(o.name) || i} className="rounded border border-slate-800/70 bg-slate-900/40 px-2.5 py-2">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-mono font-semibold text-slate-200">{asStr(o.name)}</span>
                    {asStr(o.method) && <Pill cls="bg-slate-800 text-slate-300">{asStr(o.method)}</Pill>}
                    {asStr(o.path) && <span className="font-mono text-[10px] text-slate-500">{asStr(o.path)}</span>}
                  </div>
                  <div className="mt-1 space-y-0.5 text-[11px] leading-relaxed text-slate-400">
                    {asStr(o.request) && (
                      <div>
                        <span className="text-slate-600">入参：</span>
                        {asStr(o.request)}
                      </div>
                    )}
                    {asStr(o.response) && (
                      <div>
                        <span className="text-slate-600">出参：</span>
                        {asStr(o.response)}
                      </div>
                    )}
                    {asStr(o.description) && <div className="text-slate-500">{asStr(o.description)}</div>}
                  </div>
                </div>
              )
            })}
          </div>
        </Section>
      )}

      {models.length > 0 && (
        <Section title="数据模型 Data Models" count={models.length}>
          <div className="grid gap-2 lg:grid-cols-2">
            {models.map((m, i) => {
              const o = asObj(m)
              const fields = asArr(o.fields).map(asStr).filter(Boolean)
              return (
                <div key={asStr(o.name) || i} className="rounded border border-slate-800/70 bg-slate-900/40 p-2.5">
                  <div className="font-mono text-xs font-semibold text-slate-200">{asStr(o.name)}</div>
                  {fields.length > 0 && (
                    <ul className="mt-1.5 space-y-0.5">
                      {fields.map((f, j) => (
                        <li key={j} className="font-mono text-[10px] leading-4 text-slate-400">
                          {f}
                        </li>
                      ))}
                    </ul>
                  )}
                  {asStr(o.description) && <p className="mt-1.5 text-[11px] leading-relaxed text-slate-500">{asStr(o.description)}</p>}
                </div>
              )
            })}
          </div>
        </Section>
      )}

      {(deps.length > 0 || constraints.length > 0) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {deps.length > 0 && (
            <Section title="模块依赖" count={deps.length}>
              <ul className="space-y-1">
                {deps.map((d, i) => (
                  <li key={i} className="rounded border border-slate-800/70 bg-slate-900/40 px-2.5 py-1.5 text-[11px] leading-relaxed text-slate-400">
                    {asStr(d)}
                  </li>
                ))}
              </ul>
            </Section>
          )}
          {constraints.length > 0 && (
            <Section title="约束 Constraints" count={constraints.length}>
              <ul className="space-y-1">
                {constraints.map((c, i) => (
                  <li key={i} className="rounded border border-amber-900/30 bg-amber-950/10 px-2.5 py-1.5 text-[11px] leading-relaxed text-slate-400">
                    {asStr(c)}
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>
      )}
    </div>
  )
}

// ---------- 测试报告（Tester Agent） ----------
export function TestReportView({ data }: { data: Record<string, unknown> }) {
  const passed = data.passed === true
  const s = asObj(data.summary)
  const failures = asArr(data.failures)
  const commands = asArr(data.commands).map(asStr).filter(Boolean)
  const notes = asStr(data.notes)

  const stats: Array<[string, number, string]> = [
    ['总计', asNum(s.total), 'text-slate-100'],
    ['通过', asNum(s.passed), 'text-emerald-300'],
    ['失败', asNum(s.failed), 'text-rose-300'],
    ['错误', asNum(s.errors), 'text-amber-300'],
    ['跳过', asNum(s.skipped), 'text-slate-400'],
  ]

  return (
    <div className="space-y-5">
      <div
        className={`flex items-center gap-3 rounded-lg border p-3 ${
          passed ? 'border-emerald-800/60 bg-emerald-950/20' : 'border-rose-800/60 bg-rose-950/20'
        }`}
      >
        <span className={`h-2 w-2 shrink-0 rounded-full ${passed ? 'bg-emerald-400' : 'bg-rose-400'}`} />
        <div>
          <div className={`text-sm font-semibold ${passed ? 'text-emerald-300' : 'text-rose-300'}`}>
            {passed ? '测试全部通过' : '测试未通过'}
          </div>
          <div className="text-[11px] text-slate-500">
            {asNum(s.passed)}/{asNum(s.total)} 通过
            {asNum(s.failed) > 0 && ` · ${asNum(s.failed)} 失败`}
            {asNum(s.errors) > 0 && ` · ${asNum(s.errors)} 错误`}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-5 gap-px overflow-hidden rounded-md border border-slate-800 bg-slate-800">
        {stats.map(([label, value, cls]) => (
          <div key={label} className="bg-slate-900 px-3 py-2 text-center">
            <div className={`font-mono text-lg font-semibold ${cls}`}>{value}</div>
            <div className="text-[10px] text-slate-500">{label}</div>
          </div>
        ))}
      </div>

      {failures.length > 0 && (
        <Section title="失败用例 Failures" count={failures.length}>
          <div className="space-y-1.5">
            {failures.map((f, i) => {
              const o = asObj(f)
              const line = typeof o.line === 'number' ? `:${o.line}` : ''
              return (
                <div key={i} className="rounded border border-rose-900/40 bg-rose-950/10 px-2.5 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-rose-300">{asStr(o.test)}</span>
                    {asStr(o.file) && (
                      <span className="font-mono text-[10px] text-slate-500">
                        {asStr(o.file)}
                        {line}
                      </span>
                    )}
                  </div>
                  {asStr(o.message) && (
                    <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-slate-950/70 p-2 font-mono text-[10px] leading-relaxed text-slate-400">
                      {asStr(o.message)}
                    </pre>
                  )}
                </div>
              )
            })}
          </div>
        </Section>
      )}

      {commands.length > 0 && (
        <Section title="执行命令 Commands" count={commands.length}>
          <div className="space-y-1">
            {commands.map((c, i) => (
              <div key={i} className="rounded bg-slate-950/80 px-2.5 py-1.5 font-mono text-[10px] leading-4 text-slate-400">
                $ {c}
              </div>
            ))}
          </div>
        </Section>
      )}

      {notes && (
        <Section title="备注">
          <p className="whitespace-pre-line rounded border border-slate-800/70 bg-slate-900/40 p-2.5 text-[11px] leading-relaxed text-slate-400">
            {notes}
          </p>
        </Section>
      )}
    </div>
  )
}

// ---------- 审查报告（Reviewer Agent） ----------
const SEVERITY_CLS: Record<string, string> = {
  critical: 'bg-rose-900 text-rose-200',
  high: 'bg-rose-950 text-rose-300',
  medium: 'bg-amber-950 text-amber-300',
  low: 'bg-slate-800 text-slate-400',
}

export function ReviewReportView({ data }: { data: Record<string, unknown> }) {
  const approved = data.approved === true
  const summary = asStr(data.summary)
  const issues = asArr(data.issues)
  const coverage = asArr(data.criteria_coverage).map(asStr).filter(Boolean)

  return (
    <div className="space-y-5">
      <div
        className={`flex items-center gap-3 rounded-lg border p-3 ${
          approved ? 'border-emerald-800/60 bg-emerald-950/20' : 'border-amber-800/60 bg-amber-950/20'
        }`}
      >
        <span className={`h-2 w-2 shrink-0 rounded-full ${approved ? 'bg-emerald-400' : 'bg-amber-400'}`} />
        <div>
          <div className={`text-sm font-semibold ${approved ? 'text-emerald-300' : 'text-amber-300'}`}>
            {approved ? '代码审查通过' : '审查未通过 / 有待办问题'}
          </div>
          <div className="text-[11px] text-slate-500">{issues.length} 条问题记录</div>
        </div>
      </div>

      {summary && (
        <p className="whitespace-pre-line rounded border border-slate-800/70 bg-slate-900/40 p-3 text-xs leading-relaxed text-slate-400">
          {summary}
        </p>
      )}

      {issues.length > 0 && (
        <Section title="问题清单 Issues" count={issues.length}>
          <div className="space-y-1.5">
            {issues.map((it, i) => {
              const o = asObj(it)
              const line = typeof o.line === 'number' ? `:${o.line}` : ''
              const severity = asStr(o.severity) || 'low'
              return (
                <div key={i} className="rounded border border-slate-800/70 bg-slate-900/40 px-2.5 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Pill cls={SEVERITY_CLS[severity] ?? SEVERITY_CLS.low}>{severity.toUpperCase()}</Pill>
                    {asStr(o.file) && (
                      <span className="font-mono text-[10px] text-slate-500">
                        {asStr(o.file)}
                        {line}
                      </span>
                    )}
                  </div>
                  <p className="mt-1.5 text-xs leading-relaxed text-slate-300">{asStr(o.problem)}</p>
                  {asStr(o.suggestion) && (
                    <p className="mt-1 text-[11px] leading-relaxed text-emerald-400/80">建议：{asStr(o.suggestion)}</p>
                  )}
                </div>
              )
            })}
          </div>
        </Section>
      )}

      {coverage.length > 0 && (
        <Section title="验收标准覆盖 Criteria Coverage" count={coverage.length}>
          <ul className="space-y-1">
            {coverage.map((c, i) => (
              <li key={i} className="flex items-start gap-2 text-[11px] leading-relaxed text-slate-400">
                <span className="text-emerald-500">✓</span>
                <span className="min-w-0 flex-1">{c}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  )
}

// ---------- 最终报告（Final Review） ----------
export function FinalReportView({ data }: { data: Record<string, unknown> }) {
  const ready = data.ready_for_approval === true
  const tasksTotal = asNum(data.tasks_total)
  const tasksCompleted = asNum(data.tasks_completed)
  const testsPassed = data.tests_passed === true
  const reviewApproved = data.review_approved === true
  const changedFiles = asArr(data.changed_files).map(asStr).filter(Boolean)
  const summary = asStr(data.summary)
  const blockers = asArr(data.blockers).map(asStr).filter(Boolean)

  const checks: Array<[string, boolean]> = [
    ['测试通过', testsPassed],
    ['审查通过', reviewApproved],
    [`任务完成 ${tasksCompleted}/${tasksTotal}`, tasksTotal > 0 && tasksCompleted >= tasksTotal],
  ]

  return (
    <div className="space-y-5">
      <div
        className={`flex items-center gap-3 rounded-lg border p-3 ${
          ready ? 'border-emerald-800/60 bg-emerald-950/20' : 'border-amber-800/60 bg-amber-950/20'
        }`}
      >
        <span className={`h-2 w-2 shrink-0 rounded-full ${ready ? 'bg-emerald-400' : 'bg-amber-400'}`} />
        <div>
          <div className={`text-sm font-semibold ${ready ? 'text-emerald-300' : 'text-amber-300'}`}>
            {ready ? '已就绪，等待人工审批' : '尚未就绪'}
          </div>
          <div className="text-[11px] text-slate-500">最终汇总报告（Final Review）</div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-px overflow-hidden rounded-md border border-slate-800 bg-slate-800">
        {checks.map(([label, ok]) => (
          <div key={label} className="bg-slate-900 px-3 py-2.5 text-center">
            <div className={`text-lg ${ok ? 'text-emerald-400' : 'text-rose-400'}`}>{ok ? '✓' : '✗'}</div>
            <div className="text-[10px] text-slate-500">{label}</div>
          </div>
        ))}
      </div>

      {summary && (
        <Section title="总结">
          <p className="whitespace-pre-line rounded border border-slate-800/70 bg-slate-900/40 p-3 text-xs leading-relaxed text-slate-400">
            {summary}
          </p>
        </Section>
      )}

      {changedFiles.length > 0 && (
        <Section title="变更文件" count={changedFiles.length}>
          <div className="space-y-1">
            {changedFiles.map((f, i) => (
              <div key={i} className="rounded bg-slate-950/80 px-2.5 py-1.5 font-mono text-[10px] leading-4 text-slate-400">
                {f}
              </div>
            ))}
          </div>
        </Section>
      )}

      {blockers.length > 0 && (
        <Section title="阻断项 Blockers" count={blockers.length}>
          <ul className="space-y-1">
            {blockers.map((b, i) => (
              <li key={i} className="rounded border border-rose-900/40 bg-rose-950/10 px-2.5 py-1.5 text-[11px] leading-relaxed text-rose-300/90">
                {b}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  )
}
