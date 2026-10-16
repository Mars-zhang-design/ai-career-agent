# AI Career Assistant / Resume Agent

在原有 FastAPI + JWT + MySQL 简历优化业务上加入 LangGraph 单 Agent。
目标是可解释、可测试的业务工具编排，不需要多 Agent、消息队列或复杂框架。

## 启动

建议使用独立 Python 3.11+ 环境，在 PyCharm 中为本项目选中该解释器。
不要直接覆盖已有 `.env`；只需对照 `.env.example` 补充缺少的配置。

```powershell
python -m venv .venv-agent
.\.venv-agent\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv-agent\Scripts\python.exe -m pip check
.\.venv-agent\Scripts\python.exe -m unittest discover -s tests -v
.\.venv-agent\Scripts\python.exe -m uvicorn main:app --reload
```

以上命令在项目目录运行；若已有 .venv-agent，跳过创建步骤。PyCharm 解释器选择该目录下的 Scripts/python.exe。

打开 http://127.0.0.1:8000/docs 。保持现有 MySQL 库及表不变。
需要现有 users、resumes、job_descriptions、optimization_records 表；本次不执行迁移、建表或写入演示数据。
具体字段沿用原 SQL。新环境需要从原数据库导出经审查的 schema，不能从这份代码假定完整约束。
Redis 默认 localhost:6379，可用 REDIS_URL 配置。不可用时 Agent 可执行，但任务摘要不可查询。
RAG 首次使用需要本地 embedding 模型；未缓存时 sentence-transformers 会下载模型。

本次依赖验证使用独立环境，不修改原全局 Python。全局旧 mysql-connector-python 8.0.33
依赖 protobuf 3.20.3，与当前向量库相关依赖冲突；项目清单改用 9.7.0 和 protobuf 6.33.6。
Docker 使用 Python 3.11，`.dockerignore` 排除 `.env`，运行时注入环境变量。

```powershell
docker build -t mini-job-agent .
docker run --rm -p 8000:8000 --env-file .env mini-job-agent
```

容器中的 localhost 指容器本身：MySQL/Redis 连接到宿主机时，需调整对应主机配置。
Docker 构建尚未实测，不把依赖解析成功等同于镜像已验证。

## 现有接口

- POST /auth/register、POST /auth/login、GET /auth/me：保留原流程。
- POST /resumes、POST /job-descriptions：使用登录用户身份创建数据。
- POST /resume/optimize：原文输入，返回原优化字段，不保存。
- POST /resume/optimize-by-id：鉴权、读取本人记录、优化、保存，成功响应保持原字段。
- POST /resume/agent：兼容原文输入和 status/message/result 包装，不保存。
- POST /rag：保留 answer/sources。

原文优化、原文 Agent 和 RAG 接口沿用现有未鉴权行为。公开部署前需为这些付费调用入口加鉴权、配额或限流。
旧优化函数现在先分析再改写，可能增加模型调用数量；返回契约保持一致。
原文 Agent 仍默认优化，分析/条件优化请使用下面的新接口及明确 mode。

## 新 Agent 接口

`POST /resume/agent-by-id`，需 `Authorization: Bearer <登录得到的 token>`。

```json
{
  "resume_id": 1,
  "job_description_id": 1,
  "instruction": "分析我与岗位的匹配程度，匹配度足够时优化措辞，不增加经历",
  "mode": "conditional",
  "match_threshold": 60,
  "use_knowledge": true
}
```

上面的 ID 仅为请求格式示例，调用时必须替换为你实际创建且属于当前用户的记录 ID。
mode 是服务端执行契约，优先于 instruction 中对分支的描述：

| mode | 行为 |
|---|---|
| analyze | 只分析，不优化、不创建优化记录 |
| optimize | 分析后优化，通过校验才保存 |
| conditional | 分数达到 match_threshold 才优化并保存，否则只返回分析 |

结果包含 task_id、status、analysis、optimization、record_id、saved、warnings、errors、steps。
模型不生成最终成功状态或数据库记录 ID，这些来自真实执行结果。
失败也返回同样的结构：记录不存在/越权为 404，任务超时为 504，其他工具失败为 502。
输入模型校验失败仍为 FastAPI 默认的 422 响应。

`GET /tasks/{task_id}` 只允许查询当前用户命名空间内的 Redis 摘要，TTL 为 600 秒。
返回工具名称、耗时和状态，不保存简历、JWT 或模型文本。Redis 故障为 503，过期或未找到为 404。
这是同步执行 API，task_id 随最终响应返回；不是提交后立刻返回的后台任务队列。
兼容的 POST /task/start 现在需要鉴权，拒绝为别的用户创建状态，仅创建 idle 摘要，不声称后台已启动。

## 架构与决策

```text
FastAPI 鉴权 / 参数校验
  -> resume_agent.py 初始化任务
  -> LangGraph: decide -> tools -> decide ... -> END
  -> 已验证 State 生成响应
```

- agent_state.py：类型明确的任务状态、结果、期限、错误和执行轨迹。
- agent_graph.py：状态前置条件、结构化模型决策、条件路由、失败降级和执行上限。
- agent_tools.py：六个真实工具；身份固定在只读 ToolContext 中，不由模型提供。
- repositories.py：带 user_id 限制的 SQL，短连接；保存时再次检查两条记录归属。
- resume_optimizer.py：分析/改写分离，统一 Pydantic 模型，兼容旧调用入口。
- llm_service.py：统一模型超时、有限重试和结构化解析。
- rag_chroma.py：线程锁下延迟初始化，返回片段及来源；按需问答。
- task_store.py：Redis 摘要，不是可恢复 checkpoint。

六个工具是 get_resume、get_job_description、analyze_match、retrieve_job_knowledge、
optimize_resume、save_optimization_result。读取和保存属于强制业务步骤。
在可选择“检索资料 / 继续分析或优化”时，模型根据中间状态给出经过 Pydantic 校验的动作；
代码检查动作白名单和前置条件后执行。它是受约束的单 Agent 图，不依赖任意函数调用或多 Agent 对话。

数据读取后关闭连接，再调用模型；结果校验通过后才重新开连接保存。
知识片段进入分析和优化的输入，但不能作为个人经历的证据。
分数仅作辅助判断，不是经过校准的录用概率。

## 可靠性与边界

- 工具调用上限 10 次；图 recursion_limit=32 兜底，最多修正一次不安全改写。
- 模型调用最多尝试 3 次，单次最多 15 秒；SDK 自动重试关闭，避免重试相乘。
- 整体预算 120 秒，在节点及每次模型尝试前检查。同步 embedding 初始化/计算和正在进行的数据库操作
  不能被这一软期限强制取消，因此它不是严格的 HTTP 120 秒硬超时；生产硬取消需独立 worker/process。
- 决策失败回退到允许列表中的确定性步骤；检索失败标记 warning 后继续。
- 数据缺失、分析/改写失败会终止，不能生成占位简历或假结果。
- 保存不自动重试，避免提交确认丢失导致重复插入。save_failed 表示保存未确认，需查库核对。
- 当前只保证一次任务中不重复保存；跨请求幂等和断点恢复没有实现。
- 事实校验检查原句是否存在、缺失技能是否被写入及结果结构；不能证明所有语义事实。
  保守字符串校验可能误报，校验两次仍失败则停止，不保存有问题的结果。
- 原业务表只保存分数和优化简历，完整分析在响应中；Redis 只保留短期执行摘要。
- Chroma 索引为进程内索引，重启重建，不声称持久化知识索引；knowledge.txt 仍是原有示例岗位资料。
- 应用日志只记录任务 ID、工具名称、耗时/错误类型，不输出模型原文或异常中可能携带的秘密。

## 验证

测试使用 unittest + FastAPI TestClient 和显式测试替身；禁用 dotenv，使用仅供测试的密钥。
不调用 DeepSeek，不向现有 MySQL/Redis 写入，不下载 embedding 模型。
覆盖鉴权、登录密码校验、跨用户访问、阈值分支、知识传递、检索失败、保存失败、有限修正和执行上限。
真实 DeepSeek、MySQL 表约束、Redis 服务、embedding 检索质量及 Docker 仍需在你的运行环境联调。

本次验收：36 项离线回归测试通过，14 个 Python 文件语法检查通过；独立验证环境 pip check 无冲突，Chroma、sentence-transformers 和 MySQL 驱动导入成功。验证环境复用系统中已有库，只在独立环境安装了驱动和 protobuf 修正版本；尚未执行全新环境的完整安装或 Docker 构建。


## 网页操作（Streamlit）

保持后端运行，在另一个项目终端执行：

```powershell
python -m pip install -r requirements-web.txt
python -m streamlit run web_app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

打开 http://127.0.0.1:8501 ，用已有账号登录。填写简历和岗位后分别保存，选择处理方式并开始处理。
完成后切换「查看结果」，可查看差距、改写前后对比、复制和下载简历。
网页会调用真实后端；点击「开始处理」会调用 DeepSeek 并可能保存优化记录。

- 页面只通过 HTTP 调用 FastAPI；不直接读写数据库或读取 API 密钥。
- 默认后端地址 http://127.0.0.1:8000 ，可通过启动进程的 CAREER_API_URL 环境变量调整。
- 登录凭证仅放在当前 Streamlit 会话中，不缓存到文件或全局对象；退出登录会清除草稿、结果和凭证。
- 修改资料后必须重新保存，才能运行；旧结果会明确标注。
- 网络超时不会自动重发，避免重复调用或重复写入。
- 当前没有已保存资料列表：新会话需要重新填写并保存，后续可扩展个人资料选择。
- 前端测试使用 Streamlit AppTest 与 HTTP 替身，没有使用真实账号或触发付费调用。


## 有依据的分段改写

优化工具现在将简历按非空行编号并保留原文位置，模型选择最多 6 段进行局部改写。
每项返回原段问题、修改理由、原段逐字引用及岗位逐字引用，页面在改写卡片内展示。
只有引用与原文相符、数字和熟练度表述未改变、且存在实际改动时，才按位置合并成完整简历。
未选中的文字和换行保持原样；不会让模型重新生成整份简历。
短于 20 字的行受保护；长行视为一个段落，暂不支持 PDF 布局解析或跨段重组。
一批修改验证失败时带具体反馈最多再生成一次，共用任务期限，不对每一段分别调用模型。
API 原有字段保留，rewrite_suggestions 增加 segment_id / issue / reason / evidence / jd_evidence。
分析评分、资料历史、多轮追问本次未重做。当前表仍只保存分数与最终正文，理由和引用保留在本次响应与页面会话中。

固定离线案例见 tests/test_segments.py，覆盖引用捏造、跨段借用证据、数字变化、熟练度变化、
重复原段定位、合并完整性、反馈修复及失败终止。这些测试证明程序约束，不能证明模型的语义质量或投递效果。
人工评审应分别检查：事实忠实、岗位相关性、表达清晰度，以及修改理由是否真正成立；
引用存在不等于语义一定正确。真实模型效果需用相同输入做前后对照，不以接口成功率替代质量评估。


## 职业成长工作台（新主流程）

页面分为「资料与任务 / 匹配分析 / 对话补充 / 能力计划 / 简历与结果」。
上传或粘贴资料并保存后，点击「分析岗位与能力差距」。原有模式和 RAG 选项保留在折叠区。

1. `/career/review` 逐项提取 JD，区分技能、实践、学历/年限、语言，以及必备/加分/举例。
2. 总分由代码汇总：必备3、加分1、举例0；有证据1、部分0.5、未体现/差距0。
   未体现不等于不会。证据覆盖度是非待确认项的权重占比，不是外部认证的能力证明。
   模型仍负责语义判定，因此新一轮提取仍可能变化；同一报告内权重固定，对话只更新状态。
3. `/career/chat` 根据最新用户消息提出待确认补充，逐字核对自述引用；不会自动改分。
   `/career/confirm` 在用户确认后更新状态并使旧能力计划失效。用户自述单独标识，不冒充外部验证。
4. `/career/plan` 为待补齐的技能/实践要求生成行动、交付物和验收标准；非技能条件单独展示。
   完成后在对话说明实际成果，再确认事实。没有自动代码审计或第三方成果认证。
5. `/career/polish` 使用通用表达标准美化当前简历，仍做分段事实检查，并写入原优化记录表。
6. `/career/target` 合成当前经历和带明确标记的目标补充模板，不创造已完成的经历，不写入优化记录。
7. `/career/resume` 仅在明确点击保存后，把用户确认的实际补充追加到新简历，不覆盖旧记录。

本版本不增加 MySQL 表。报告、最多12条近期对话和计划通过带24小时有效期的签名状态在页面会话中传递；
每次请求检查当前账号、原始数据归属和内容摘要。签名防止修改，但不是加密：状态含个人信息，不能分享或记录到日志。
刷新、登出或关闭页面可能丢失会话，完整聊天历史和跨设备恢复尚未实现。正式产品后续应增加数据库会话持久化。
用户打开旧的本人报告仍可查看旧状态；本版不是跨浏览器并发编辑系统。

文件导入支持 TXT/MD、DOCX、文字PDF，最多5MB，PDF最多30页，提取文字最多4万字。
扫描件没有OCR，不支持旧DOC或图片。文件只在内存中提取，用户核对并点击保存后才把文字写入MySQL。
PDF依赖写在 requirements-web.txt。本次仅在项目的 .web-libs/ 安装PDF依赖供当前页面使用，没有修改全局Python。

测试：test_career.py 覆盖固定评分、引用验证、状态签名与账号绑定、假设阻断、人为确认、计划覆盖、目标与正式简历隔离；
test_career_ui.py 覆盖新页面的对话、确认、资料失效及导出流程。离线测试不调用付费模型，也不写真实业务记录。
