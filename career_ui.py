"""Compact career workspace panels; calls only authenticated HTTP endpoints."""
import streamlit as st
from web_client import ApiError
import ui_theme
from career_workflow import has_plan_candidates

STATUS = {"supported":"已有证据", "partial":"部分满足", "unknown":"未体现 · 待确认", "gap":"明确差距"}
IMPORTANCE = {"required":"必备", "preferred":"加分", "example":"举例（不计分）"}
CATEGORY = {"skill":"技能", "experience":"实践经验", "qualification":"学历 / 年限", "language":"语言条件"}


def remember(value):
    st.session_state["career"] = value
    st.session_state.pop("target_resume", None)
    st.session_state.pop("promoted_resume", None)
    st.session_state.pop("workflow_result", None)
    # A changed report does not make the original resume or older polish change.


def current(context):
    value = st.session_state.get("career")
    if not value:
        st.info("先在「① 对照岗位」放入简历和岗位，点击「分析岗位与能力差距」。")
        return None
    if st.session_state.get("career_context") != context:
        st.warning("资料已修改，请保存并重新分析后继续对话或生成计划。")
        return None
    return value


def invoke(api, handle_error, path, extra=None):
    try:
        with st.spinner("正在处理，请稍候……"):
            value = api("POST", path, {"report_token": st.session_state["career"]["report_token"], **(extra or {})})
        return value
    except ApiError as exc:
        handle_error(exc)
        return None


def analysis_panel(context):
    value = current(context)
    if not value:
        return
    report = value["report"]
    a,b,c = st.columns(3)
    a.metric("岗位证据匹配度", f"{report['score']} / 100")
    b.metric("已明确的要求", f"{report['evidence_coverage']}%")
    c.metric("待确认", sum(r['status']=='unknown' for r in report['requirements']))
    st.caption("未体现不代表不会；分数反映当前简历证据，不代表录用概率。")
    with st.expander("评分怎么得出？"):
        st.write("必备权重3、加分权重1、举例不计分；满足得全额、部分满足得一半。未体现暂不得分。")
        st.write("每项得分相加 ÷ 所有计分项权重 × 100。模型负责提取和判断证据，程序负责汇总；提取和语义判断仍可能出错，可在对话中纠正。不是录用概率。")
        st.write("已明确的要求表示非待确认项所占权重，不是第三方认证的能力比例。")
    rows = report["requirements"]
    ui_theme.next_step(report)
    view = st.radio("查看要求", ["需要关注", "已满足", "全部"], horizontal=True, key="requirement_view")
    visible = [r for r in rows if view == '全部' or (view == '已满足' and r['status'] == 'supported') or (view == '需要关注' and r['status'] != 'supported' and r['importance'] != 'example')]
    if not visible:
        st.caption("当前分类没有要求，可切换到其他分类查看。")
    for index, row in enumerate(sorted(visible, key=lambda r: (r['importance'] != 'required', r['status'] == 'supported'))):
        with st.container(border=True, key=f'requirement_card_{index}'):
            st.markdown(f"**{row['title']}**")
            st.caption(f"{CATEGORY[row['category']]} · {IMPORTANCE[row['importance']]} · {STATUS[row['status']]} · {row['points']:g}/{row['weight']} 分")
            st.write(row['explanation'])
            with st.expander("岗位要求与个人证据"):
                st.write("岗位原文")
                st.text(row['jd_quote'])
                for quote in row.get('resume_quotes',[]):
                    st.text(quote)
                if row.get('user_statement'):
                    st.write("本人确认的补充（未经第三方验证）")
                    st.text(row['user_statement'])
            if row['status'] in ('partial','unknown') and row.get('question'):
                st.caption(row['question'])
    for warning in report.get('warnings',[]):
        st.warning(warning)


def conversation_panel(context, api, handle_error):
    value = current(context)
    if not value:
        return
    report = value['report']
    st.subheader("把简历没写清楚的部分聊清楚")
    st.caption("可以补充经历、提交实践成果或纠正判断。核对并确认后，差距与目标清单会随之更新。")
    with st.container(height=390, border=True):
        for message in report['messages']:
            with st.chat_message(message['role']):
                st.write(message['content'])
    message = st.chat_input("例如：我做过工具调用，具体实现了……", key="career_chat", max_chars=4000)
    if message:
        result = invoke(api,handle_error,'/career/chat',{'message':message})
        if result:
            remember(result)
            st.rerun()
    if report.get('pending'):
        st.subheader("这些补充是否准确？")
        labels={r['id']:r['title'] for r in report['requirements']}
        for i,proposal in enumerate(report['pending']):
            with st.container(border=True):
                st.write("**" + labels.get(proposal['requirement_id'],'要求') + " → " + STATUS[proposal['status']] + "**")
                st.text(proposal['statement'])
                st.caption(proposal['reason'])
                a,b=st.columns(2)
                accepted=a.button("准确，确认更新",key=f"confirm_{report['revision']}_{i}",use_container_width=True)
                rejected=b.button("不准确，忽略",key=f"reject_{report['revision']}_{i}",use_container_width=True)
                if accepted or rejected:
                    result=invoke(api,handle_error,'/career/confirm',{'proposal_index':i,'accept':accepted})
                    if result:
                        remember(result)
                        if result['report'].get('agent', {}).get('enabled') and not result['report'].get('pending'):
                            # Save the confirmed result locally before continuing: a failed
                            # request must never lose the user's explicit confirmation.
                            continued = invoke(api, handle_error, '/career/advance')
                            if continued:
                                remember(continued)
                            else:
                                st.session_state['workflow_result'] = {'context': context, 'plan_state': 'failed',
                                    'plan_error': '补充已确认，后续任务暂未完成，可在目标清单继续。'}
                        st.rerun()



REFERENCE_STATUS = {
    'cited': '已引用知识资料；任务仍是学习建议，不代表官方认证或已具备能力。',
    'uncited': '一般学习建议：本任务未引用知识资料，请自行核对。',
    'empty': '一般学习建议：知识库没有可用参考资料。',
    'unavailable': '一般学习建议：生成时知识检索不可用，未引用资料，请自行核对。',
}


def plan_export(report):
    lookup = {r['id']: r for r in report['requirements']}
    blocks = ['能力补齐计划｜待完成任务，不是已完成经历']
    for task in report.get('tasks', []):
        row = lookup[task['requirement_id']]
        lines = [row['title'], '岗位原文：' + row['jd_quote'], '当前判断：' + STATUS[row['status']],
                 '已有简历证据：' + ('；'.join(row.get('resume_quotes', [])) or '暂无直接引用')]
        if row.get('user_statement'):
            lines.append('本人确认的自述（未经第三方验证）：' + row['user_statement'])
        lines += [task['objective'], *task['actions'], '交付：' + task['deliverable'],
                  '验收：' + '；'.join(task['acceptance']),
                  REFERENCE_STATUS.get(task.get('reference_status'), REFERENCE_STATUS['uncited'])]
        for reference in task.get('references', []):
            lines += ['参考：' + reference['title'], reference['source_url'],
                      '资料更新日期：' + reference.get('updated_at', ''), '参考片段：' + reference['excerpt']]
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


def checklist_panel(context, api, handle_error):
    value = current(context)
    if not value:
        return
    report = value['report']
    st.subheader("目标清单：改善后再投递")
    st.caption("分析后自动整理。先确认未写清楚的经历，再补齐真实差距；需要具体做法时生成行动计划。")
    agent = report.get('agent', {})
    if agent.get('status') == 'failed':
        st.warning(agent.get('note') or '本轮安排暂未完成，已完成的内容已保留。')
    elif agent.get('status') == 'waiting':
        st.info(agent.get('note') or '可以先补充经历，也可以跳过提问直接生成计划。')
    eligible = has_plan_candidates(report)
    can_skip = agent.get('status') == 'waiting' and agent.get('next_action') == 'clarify'
    label = '跳过提问，查看清单' if can_skip and not eligible else '生成 / 更新行动计划'
    if st.button(label, type="primary", disabled=not (eligible or can_skip) or bool(report.get('pending')),
                 help="直接安排尚缺的任务，跳过未回答的提问；已有且仍适用的计划会保留。"):
        result = invoke(api, handle_error, '/career/advance', {'skip_clarification': True})
        if result:
            remember(result)
            st.rerun()
    if report.get('pending'):
        st.caption('先在「② 看清差距」确认或忽略待核对的补充，再更新计划。')
    from career_models import CareerReport
    from target_preview import build_target_preview
    preview = build_target_preview(CareerReport.model_validate(report), context[0]['resume_text'])
    target_preview_panel(preview, {task['requirement_id']: task for task in report.get('tasks', [])})
    st.caption("完成实践后，到「② 看清差距 → 补充经历 / 纠正判断」说明实际成果并确认，重新评估当前差距。")


def target_preview_panel(result, tasks=None):
    tasks = tasks or {}
    st.caption("待完成是改善方向；待确认是简历证据不足，不代表你不会。清单不自动修改简历。")
    items = result['items']
    completed = sum(item['status'] == 'complete' for item in items)
    a, b, c = st.columns(3)
    a.metric("目标事项", len(items))
    b.metric("待完成", completed)
    c.metric("待确认", len(items) - completed)
    if not items:
        st.success("当前没有待完成或待确认事项。可核对真实经历与岗位条件后准备投递。")
    else:
        choice = st.radio("筛选目标事项", ["全部", "待完成", "待确认"], horizontal=True, key="target_status_filter")
        shown = [item for item in items if choice == '全部' or
                 item['status'] == ('complete' if choice == '待完成' else 'confirm')]
        if not shown:
            st.info("这个分类下暂无事项。")
        for index, item in enumerate(shown):
            with st.container(border=True, key=f'goal_card_{index}'):
                ui_theme.status_label(item['status_label'], item['status'])
                st.subheader(item['title'])
                st.write("下一步：" + item['next_step'])
                task = tasks.get(item['requirement_id'])
                if task:
                    if item['status'] == 'confirm':
                        st.info("这项尚未确认缺失。如果已有相关经历，先补充；以下计划供确认确有差距后使用。")
                    st.write(task['objective'])
                    for i, action in enumerate(task['actions'], 1):
                        st.write(f"{i}. {action}")
                    st.write("**交付成果：** " + task['deliverable'])
                    with st.expander("验收标准与学习参考"):
                        for check in task['acceptance']:
                            st.write("• " + check)
                        status = task.get('reference_status', 'uncited')
                        note = REFERENCE_STATUS.get(status, REFERENCE_STATUS['uncited'])
                        (st.warning if status == 'unavailable' else st.caption)(note)
                        for reference in task.get('references', []):
                            with st.expander("学习参考：" + reference['title']):
                                st.text(reference['excerpt'])
                                st.caption("资料更新日期：" + reference.get('updated_at', '未注明'))
                                st.link_button("查看来源文档", reference['source_url'])
                with st.expander("查看岗位依据与待确认内容"):
                    st.text(item['jd_quote'])
                    if item.get('question'):
                        st.write("需要确认：" + item['question'])
    with st.expander("分析依据：原简历与已确认经历"):
        st.text(result.get('current_resume', ''))
        for addition in result.get('confirmed_additions', []):
            st.text("本人确认的补充：" + addition)
    from target_preview import export_target_checklist
    st.download_button("下载目标清单", export_target_checklist(result).encode('utf-8-sig'),
                       file_name="目标岗位改善清单.txt", mime="text/plain")
    if tasks:
        # Include full actions, references and acceptance in the detailed export.
        report = st.session_state['career']['report']
        st.download_button("下载详细行动计划", plan_export(report).encode('utf-8-sig'),
                           file_name="岗位改善行动计划.txt", mime="text/plain")
