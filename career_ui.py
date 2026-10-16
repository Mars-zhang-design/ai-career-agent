"""Compact career workspace panels; calls only authenticated HTTP endpoints."""
import streamlit as st
from web_client import ApiError

STATUS = {"supported":"已有证据", "partial":"部分满足", "unknown":"未体现 · 待确认", "gap":"明确差距"}
IMPORTANCE = {"required":"必备", "preferred":"加分", "example":"举例（不计分）"}
CATEGORY = {"skill":"技能", "experience":"实践经验", "qualification":"学历 / 年限", "language":"语言条件"}


def remember(value):
    st.session_state["career"] = value
    st.session_state.pop("target_resume", None)
    st.session_state.pop("promoted_resume", None)
    # A changed report does not make the original resume or older polish change.


def current(context):
    value = st.session_state.get("career")
    if not value:
        st.info("先在「资料与任务」保存简历和岗位，再点击「分析岗位与能力差距」。")
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
    st.caption("必备权重3、加分权重1、举例不计分；满足得全额、部分满足得一半。未体现暂不得分，不代表不会。")
    with st.expander("评分怎么得出？"):
        st.write("每项得分相加 ÷ 所有计分项权重 × 100。模型负责提取和判断证据，程序负责汇总；提取和语义判断仍可能出错，可在对话中纠正。不是录用概率。")
        st.write("已明确的要求表示非待确认项所占权重，不是第三方认证的能力比例。")
    for row in report["requirements"]:
        with st.container(border=True):
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
    st.caption("可以补充经历、纠正判断或询问学习方向。补充先确认，不会自动写入简历。")
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
                        st.rerun()


def plan_panel(context, api, handle_error):
    value=current(context)
    if not value:
        return
    report=value['report']
    st.subheader("把差距变成可完成的任务")
    st.caption("先确认是否真的缺失，再学习或实践。完成后，到「对话补充」说明实际做了什么并提交成果说明。")
    if st.button("生成 / 更新能力计划",type="primary"):
        result=invoke(api,handle_error,'/career/plan')
        if result:
            remember(result)
            st.rerun()
    lookup={r['id']:r for r in report['requirements']}
    for task in report.get('tasks',[]):
        row=lookup[task['requirement_id']]
        with st.container(border=True):
            st.markdown("**" + row['title'] + "** · " + IMPORTANCE[row['importance']])
            if row['status']=='unknown':
                st.info("这项尚未确认缺失。如果你已经有相关经历，先在对话里补充。")
            st.write(task['objective'])
            for i,action in enumerate(task['actions'],1):
                st.write(f"{i}. {action}")
            st.write("**交付成果：** " + task['deliverable'])
            st.write("**验收标准**")
            for check in task['acceptance']:
                st.write("• " + check)
    if not report.get('tasks'):
        st.info("暂无能力计划。点击上方按钮生成；确认能力发生变化后，旧计划会清空，需更新。")
    conditions=[r for r in report['requirements'] if r['category'] in ('qualification','language') and r['status']!='supported' and r['importance']!='example']
    if conditions:
        st.subheader("另外核对这些条件")
        for row in conditions:
            st.write("• " + row['title'] + "：" + STATUS[row['status']])
        st.caption("学历、工作年限和语言条件不能直接用一个练习项目代替。")
    if report.get('tasks'):
        text="\n\n".join(lookup[t['requirement_id']]['title']+"\n"+t['objective']+"\n"+"\n".join(t['actions'])+"\n交付："+t['deliverable']+"\n验收："+"；".join(t['acceptance']) for t in report['tasks'])
        st.download_button("下载能力计划",text.encode('utf-8'),file_name="能力补齐计划.txt",mime="text/plain")


def resume_panel(context,api,handle_error):
    value=current(context)
    if not value:
        return
    polished,target,confirmed=st.tabs(["当前简历美化","目标简历预览","已确认补充"])
    with polished:
        st.caption("只改善当前原简历的表达，不编造缺失技能；保存为优化记录，原简历不被覆盖。")
        if st.button("美化当前简历",type="primary"):
            result=invoke(api,handle_error,'/career/polish')
            if result:
                st.session_state['career_polish']={'context':context,'data':result}
        cached=st.session_state.get('career_polish',{})
        if cached.get('context')==context:
            result=cached['data']
            st.success("表达美化完成，已保存。")
            optimization=result['optimization']
            for edit in optimization['rewrite_suggestions']:
                with st.expander(edit.get('issue') or '改写对比'):
                    a,b=st.columns(2)
                    a.write("**原文**");a.write(edit['original'])
                    b.write("**美化后**");b.write(edit['optimized'])
                    st.write(edit.get('reason',''))
            st.text(optimization['optimized_resume'])
            st.download_button("下载美化简历",optimization['optimized_resume'].encode('utf-8'),file_name="美化简历.txt",mime="text/plain")
            with st.expander("复制美化简历"):
                st.code(optimization['optimized_resume'],language=None,wrap_lines=True)
    with target:
        st.caption("当前经历 + 待完成补充模板。待完成内容带明确标记，不能冒充已经做过；完成并确认后才能转入正式简历。")
        if st.button("生成目标简历预览"):
            result=invoke(api,handle_error,'/career/target')
            if result:
                st.session_state['target_resume']=result
        result=st.session_state.get('target_resume')
        if result:
            st.warning("目标版本含待完成 / 待确认事项，请勿直接作为当前事实简历投递。")
            st.text(result['text'])
            st.download_button("下载目标简历（含待完成标记）",result['text'].encode('utf-8'),file_name="目标简历_待完成.txt",mime="text/plain")
    with confirmed:
        additions=[r for r in value['report']['requirements'] if r['source']=='user_confirmed' and r['status'] in ('supported','partial')]
        for row in additions:
            st.write("**"+row['title']+"**")
            st.text(row['user_statement'])
        if not additions:
            st.info("暂无已确认的经历补充。先在对话中说明真实经历，并确认更新。")
        st.caption("仅将上述本人确认内容追加到原简历，保存为新版本；学习计划和目标模板不会加入。")
        if st.button("保存包含补充经历的新简历",disabled=not additions):
            result=invoke(api,handle_error,'/career/resume')
            if result:
                st.session_state['promoted_resume']=result
        if st.session_state.get('promoted_resume'):
            st.success("新简历已保存。下载后可在资料页导入，重新分析匹配情况。")
            st.download_button("下载包含补充的简历",st.session_state['promoted_resume']['resume_text'].encode('utf-8'),file_name="补充后简历.txt",mime="text/plain")
