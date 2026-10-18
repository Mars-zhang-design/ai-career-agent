"""Small shared visual layer; all dynamic content is escaped before HTML rendering."""
from html import escape
import streamlit as st


CSS = """<style>
:root {--accent:#13786e;--ink:#23364a;--muted:#63748a;--line:#dfe7eb;}
.stApp {background:#f5f7f9;color:var(--ink);}
.block-container {max-width:1180px;padding-top:4.25rem;padding-bottom:3rem;}
h1,h2,h3 {color:var(--ink);letter-spacing:-.025em;}
h1 {font-size:2.2rem!important;font-weight:750!important;padding-bottom:.4rem!important;}
h3 {font-size:1.2rem!important;font-weight:650!important;}
[data-testid="stHeader"] {background:rgba(245,247,249,.94);}
[data-testid="stSidebar"] {background:#edf2f5;border-right:1px solid var(--line);}
[data-testid="stSidebar"] .block-container {padding-top:1.5rem;}
[data-testid="stCaptionContainer"] {color:var(--muted);}
[data-testid="stMetric"] {background:#fff;border:1px solid var(--line);border-radius:14px;padding:.7rem 1rem;box-shadow:0 2px 7px #23364a04;}
[data-testid="stMetricValue"] {font-size:1.8rem;font-weight:650;color:var(--ink);}
[data-testid="stMetricLabel"] {color:var(--muted);font-size:.85rem;}
[data-testid="stForm"] {background:#fff;border-radius:16px;}
.stButton button,.stDownloadButton button {border-radius:10px;min-height:2.65rem;font-weight:550;transition:background .15s,border-color .15s;}
button[kind="primary"],[data-testid="stBaseButton-primary"] {background:var(--accent)!important;border-color:var(--accent)!important;color:#fff!important;}
button[kind="primary"]:hover,[data-testid="stBaseButton-primary"]:hover {background:#0e625a!important;}
button:focus-visible {outline:2px solid #147d72!important;outline-offset:3px;}
[data-baseweb="tab-list"] {gap:.4rem;background:#eaf0f3;padding:5px;border-radius:12px;margin:.65rem 0 1rem;}
[data-baseweb="tab"] {height:2.7rem;border-radius:8px;padding:0 1.1rem;color:#53667c;}
[data-baseweb="tab"][aria-selected="true"] {background:#fff;color:var(--accent);box-shadow:0 2px 5px #183c5010;font-weight:650;}
[data-baseweb="tab-highlight"],[data-baseweb="tab-border"] {display:none;}
[data-baseweb="input"],[data-baseweb="textarea"] {background:#fff;border-radius:10px;}
input:not([type="radio"]):not([type="checkbox"]),textarea {background:#fff!important;color:var(--ink)!important;}
label[data-baseweb="radio"]:has(input:checked)>div:first-child {background:var(--accent)!important;}
[data-testid="stExpander"] details {background:#fff;border:1px solid var(--line);border-radius:10px;}
[class*="st-key-goal_card_"] {background:#fff;border-radius:14px;box-shadow:0 3px 12px #23364a05;}
[class*="st-key-requirement_card_"] {background:#fff;border-radius:14px;}
.hero-kicker {color:var(--accent);font-weight:650;letter-spacing:.12em;font-size:.75rem;margin-bottom:.15rem;}
.brand-mark {display:inline-grid;place-items:center;width:32px;height:32px;background:var(--accent);border-radius:10px;color:#fff;margin-right:9px;}
.sidebar-brand {font-size:1.05rem;font-weight:700;color:var(--ink);margin-bottom:1rem;}
.workflow-pill {display:inline-block;padding:5px 10px;border-radius:7px;background:#e6f3ed;color:#1e6257;font-size:.8rem;margin:0 7px 7px 0;}
.next-step {background:#edf6f3;border:1px solid #cfe5df;border-left:4px solid var(--accent);border-radius:12px;padding:15px 18px;margin:8px 0 18px;}
.next-step small {color:#42796f;font-weight:650;}
.next-step h4 {margin:6px 0;color:#194b44;font-size:1.07rem;}
.next-step p {margin:0;color:#47675f;font-size:.9rem;line-height:1.6;}
.status-label {display:inline-block;padding:4px 9px;border-radius:6px;font-size:.78rem;font-weight:600;background:#edf2f6;color:#445e7b;}
.status-label.confirm {background:#eaf1fb;color:#315f9c;}
.status-label.complete {background:#fff1dc;color:#946020;}
@media(max-width:700px) {.block-container{padding:4rem 1rem 1.5rem;} h1{font-size:1.85rem!important;} [data-baseweb="tab"]{padding:0 .65rem;} .next-step{padding:12px;} }
@media(prefers-reduced-motion:reduce) {*{transition:none!important;}}
</style>"""


def install():
    st.markdown(CSS, unsafe_allow_html=True)


def progress_pills(progress):
    if not progress:
        return
    labels = ['差距已分析', '行动计划已生成' if progress['report'].get('tasks') else '目标清单已整理']
    if progress.get('history_saved'):
        labels.append('进度已保存')
    st.markdown(''.join('<span class="workflow-pill">' + escape(label) + '</span>' for label in labels), unsafe_allow_html=True)


def next_step(report):
    rows = [row for row in report['requirements'] if row['importance'] != 'example']
    pending = report.get('pending', [])
    unknown = [row for row in rows if row['status'] == 'unknown']
    gaps = sorted((row for row in rows if row['status'] in ('partial', 'gap')), key=lambda row: row['importance'] != 'required')
    tasks = {task['requirement_id']: task for task in report.get('tasks', [])}
    agent = report.get('agent', {})
    if pending:
        title = f'先核对 {len(pending)} 条待确认补充'
        detail = '打开下方补充对话，确认哪些内容准确，再更新能力判断。'
    elif agent.get('status') == 'failed':
        title = '已完成的内容已保留'
        detail = agent.get('note', '到目标清单重试，继续安排尚未完成的部分。')
    elif agent.get('status') == 'waiting':
        title = '先确认一两项关键经历'
        detail = agent.get('note', '在下方补充经历，也可以到目标清单跳过提问。')
    elif gaps:
        first = gaps[0]
        title = '优先关注：' + first['title']
        if first['id'] in tasks:
            detail = '下一份可验证成果：' + tasks[first['id']]['deliverable']
        elif first['category'] in ('qualification', 'language'):
            detail = '先核对岗位条件和自身情况，这类要求不能通过一个练习项目替代。'
        else:
            detail = '到「③ 目标清单」生成行动计划，把差距拆成练习、交付成果和验收标准。'
    elif unknown:
        title = f'先澄清 {len(unknown)} 项未写清楚的经历'
        detail = '可以从“' + unknown[0]['title'] + '”开始补充。未体现不代表不会，先确认再决定是否需要学习。'
    else:
        title = '已有证据覆盖较完整'
        detail = '核对真实经历与岗位条件后准备投递。匹配结果不代表录用保证。'
    st.markdown('<div class="next-step"><small>建议下一步</small><h4>' + escape(title) + '</h4><p>' + escape(detail) + '</p></div>', unsafe_allow_html=True)


def status_label(label, status):
    css = 'confirm' if status == 'confirm' else 'complete'
    st.markdown(f'<span class="status-label {css}">' + escape(label) + '</span>', unsafe_allow_html=True)
