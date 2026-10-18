"""Structured target preview. Pending goals are never phrased as completed experience."""
def build_target_preview(report, original):
    tasks = {t.requirement_id: t for t in report.tasks}
    items = []
    for row in report.requirements:
        if row.status == 'supported' or row.importance == 'example':
            continue
        check = row.status == 'unknown' or row.category in ('qualification', 'language')
        task = tasks.get(row.id)
        items.append(dict(
            requirement_id=row.id, title=row.title,
            status='confirm' if check else 'complete',
            status_label='待确认' if check else '部分满足 · 待完成' if row.status == 'partial' else '待完成',
            jd_quote=row.jd_quote,
            next_step=('到「② 看清差距」补充已有经历或条件，再确认判断。' if check else
                       '按下方行动计划完成实践，再补充真实成果并确认。' if task else
                       '点击「生成 / 更新行动计划」，明确练习和交付成果。'),
            objective=task.objective if task and not check else '',
            deliverable=task.deliverable if task and not check else '',
            acceptance=list(task.acceptance) if task and not check else [],
            question=row.question if check else '',
        ))
    additions = list(dict.fromkeys(r.user_statement for r in report.requirements
        if r.source == 'user_confirmed' and r.status in ('supported', 'partial') and r.user_statement))
    result = dict(is_target=True, pending_count=len(items),
                  current_resume=original, confirmed_additions=additions, items=items)
    result['text'] = export_target_checklist(result)
    return result


def export_target_checklist(result):
    """Plain-text sections remain clear in Notepad, printouts and copied excerpts."""
    if 'items' not in result:
        return result['text']  # Compatibility with older cached responses.
    items = result['items']
    complete = [item for item in items if item['status'] == 'complete']
    confirm = [item for item in items if item['status'] == 'confirm']
    line = '=' * 48
    parts = ['目标岗位改善清单', '非投递版｜待完成、待确认事项不是已经取得的经历',
             f'待完成：{len(complete)} 项    待确认：{len(confirm)} 项', '',
             line, '一、当前简历原文', line,
             '以下为用户原文，不代表第三方核验；目标事项未混入此区。', '',
             result.get('current_resume', ''), '',
             line, '二、本人确认的补充', line,
             '以下为本人确认的自述，未经第三方验证；与未来目标分开列出。']
    additions = result.get('confirmed_additions', [])
    parts += [f'{i}. {text}' for i, text in enumerate(additions, 1)] if additions else ['暂无本人确认的补充。']
    for heading, rows, guidance in (
        ('三、待完成事项', complete, '尚未完成，或只满足部分要求。完成实践并确认真实成果后，再据实写入简历。'),
        ('四、待确认事项', confirm, '证据或条件尚待核实，不代表你不会；先补充事实，不要直接写成已满足。'),
    ):
        parts += ['', line, f'{heading}（{len(rows)} 项）', line, guidance]
        if not rows:
            parts.append('暂无此类事项。')
        for i, item in enumerate(rows, 1):
            parts += ['', f"{i}. 【{item['status_label']}】{item['title']}", '-' * 40,
                      '下一步：' + item['next_step']]
            if item.get('question'):
                parts.append('需要确认：' + item['question'])
            if item.get('deliverable'):
                parts.append('待交付成果：' + item['deliverable'])
            if item.get('acceptance'):
                parts.append('完成后的验收标准：')
                parts += ['  - ' + check for check in item['acceptance']]
            parts.append('对应岗位原文：' + item['jd_quote'])
    parts += ['', line, '使用提醒', '此文件是准备清单，不是最终简历。请勿将待完成或待确认事项作为既有经历投递。']
    return '\n'.join(parts) + '\n'
