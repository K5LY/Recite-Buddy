#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
教材分章背诵助手 · 通用组装脚本
================================
用法:
    python3 build.py <work_dir> <out_path> [--report <md_path>]

<work_dir> 内需包含:
    config.json       书级配置（书名/考纲/配色/前缀/图标/别名/main_ids 等）
    chapters.json     章节数据（含考点/分段精读/易错点/备考要点/总结表）
    people.json       人物与作品档案（人名/生平/思想/成就/关联/插图）
    terms.json        术语条目（定义/关联/自动链接开关）
    cards.json        背诵闪卡
    threads.json      跨章知识线索
    qa.json           考点标准答案（键: {chid}-{序号}，序号从 1 开始）
    py.json           生僻字/词注音表 {kw:{词:拼音}, py:{字:拼音}}

可选 --report <md_path>: 生成「考点分配表」markdown（章节名/重要度/
判定依据/考点数量），供核对与调整；章节缺失 weight/weight_note 时
输出警告并标注「未填写」。

脚本会:
    1. 加载模板 assets/template.html（本文件同目录）
    2. 校验数据一致性（id 去重、links 指向存在、QA 覆盖考点）
    3. 注入 people kind 标记（main=受访核心人物 / side=先驱与背景人物）
    4. 转换 QA 为 {chid:{'0':'答案',...}} 嵌套结构
    5. 替换全部 {{占位符}} 生成最终单文件 HTML

退出码: 0=成功；1=校验失败（不产出）。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, 'template.html')


def load(work, name):
    path = os.path.join(work, name)
    if not os.path.exists(path):
        sys.exit(f'[build] 缺少数据文件: {path}')
    return json.load(open(path, encoding='utf-8'))


def validate(cfg, CH, WK, CD, TH, TM, QA, PY):
    """一致性校验：返回错误列表（空=通过）。"""
    errs = []
    # 1. id 唯一性
    for label, items in [('章节', CH), ('人物', WK), ('术语', TM), ('线索', TH)]:
        ids = [x['id'] for x in items]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            errs.append(f'{label} id 重复: {sorted(dup)}')
    # 2. links / terms / works 指向存在
    w_ids = {w['id'] for w in WK}
    t_ids = {t['id'] for t in TM}
    for w in WK:
        for lk in w.get('links', []):
            if lk not in w_ids and lk not in t_ids and not (lk.startswith('ch') and any(c['id'] == lk for c in CH)):
                errs.append(f'人物 {w["id"]} 的 links 指向不存在: {lk}')
    for t in TM:
        for x in t.get('terms', []) + t.get('works', []):
            if x not in t_ids and x not in w_ids:
                errs.append(f'术语 {t["id"]} 的关联指向不存在: {x}')
    for th in TH:
        for node in th.get('nodes', []):
            for x in node[2]:
                if x not in w_ids and x not in t_ids and not (x.startswith('ch') and any(c['id'] == x for c in CH)):
                    errs.append(f'线索 {th["id"]} 节点指向不存在: {x}')
    # 3. QA 覆盖：每章 exam 考点都应有关键词命中的答案条目（宽松检查：条数对齐）
    ch_exam_count = {c['id']: len(c.get('exam', [])) for c in CH}
    qa_by_ch = {}
    for k in QA:
        chid, idx = k.rsplit('-', 1)
        qa_by_ch.setdefault(chid, []).append(int(idx))
    for cid, n in ch_exam_count.items():
        if n and cid not in qa_by_ch:
            errs.append(f'章节 {cid} 有 {n} 个考点但 qa.json 无答案条目')
        elif n and len(qa_by_ch[cid]) < n:
            errs.append(f'章节 {cid} 考点 {n} 条但答案仅 {len(qa_by_ch[cid])} 条')
    # 4. 注音 key 唯一性（kw 与 py 不冲突即可，允许重复）
    return errs


def write_report(CH, QA, path):
    """考点分配表：章节名 / 重要度 / 判定依据 / 考点数量。"""
    qa_cnt = {}
    for k in QA:
        chid, _ = k.rsplit('-', 1)
        qa_cnt[chid] = qa_cnt.get(chid, 0) + 1
    lines = ['# 考点分配表', '', '| 章节 | 重要度 | 判定依据 | 考点数 | QA 条数 |', '|---|---|---|---|---|']
    total = 0
    wstats = {}
    for c in CH:
        w = c.get('weight', '未填写')
        note = c.get('weight_note', '未填写')
        n = len(c.get('exam', []))
        total += n
        wstats[w] = wstats.get(w, 0) + 1
        if w == '未填写':
            print(f'[build] 警告: 章节 {c["id"]} {c.get("no","")} 缺少 weight/weight_note，请在 chapters.json 补填')
        lines.append(f'| {c.get("no","")} {c.get("title","")} | {w} | {note} | {n} | {qa_cnt.get(c["id"], 0)} |')
    lines += ['', f'**合计：{total} 个考点**；章节分布：' +
              ' / '.join(f'{k} {v} 章' for k, v in wstats.items())]
    open(path, 'w', encoding='utf-8').write('\n'.join(lines))
    print('[build] 考点分配表:', path)


def main():
    args = sys.argv[1:]
    report_path = None
    if '--report' in args:
        i = args.index('--report')
        report_path = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    work, out = args[0], args[1]
    cfg = load(work, 'config.json')
    CH = load(work, 'chapters.json')
    WK = load(work, 'people.json')
    CD = load(work, 'cards.json')
    TH = load(work, 'threads.json')
    TM = load(work, 'terms.json')
    PY = load(work, 'py.json')
    qa0 = load(work, 'qa.json')

    # QA 嵌套转换: {"ch01-1": {...}} -> {"ch01": {"0": {...}, "1": {...}}}
    QA = {}
    for k, v in qa0.items():
        chid, idx = k.rsplit('-', 1)
        QA.setdefault(chid, {})[str(int(idx) - 1)] = v

    # 人物 kind: main=受访核心人物（cfg.main_ids），side=先驱与背景人物
    main_ids = set(cfg.get('main_ids', []))
    for w in WK:
        w['kind'] = 'main' if w['id'] in main_ids else 'side'

    # 校验（QA 用原始 {chid-序号} 键格式）
    errs = validate(cfg, CH, WK, CD, TH, TM, qa0, PY)
    if errs:
        for e in errs:
            print('[build] 校验失败:', e)
        sys.exit(1)

    # QA 嵌套转换: {"ch01-1": {...}} -> {"ch01": {"0": {...}, "1": {...}}}

    tpl = open(TPL, encoding='utf-8').read()
    rep = {
        '{{CH}}': CH, '{{WK}}': WK, '{{CD}}': CD, '{{TH}}': TH,
        '{{TM}}': TM, '{{QA}}': QA, '{{PY}}': PY,
        '{{TITLE}}': cfg['title'], '{{BADGE}}': cfg['badge'],
        '{{OVERVIEW}}': cfg['overview'], '{{OVERVIEW2}}': cfg.get('overview2', ''),
        '{{C1}}': cfg['c1'], '{{C2}}': cfg['c2'],
        '{{C1HEX}}': cfg['c1'].lstrip('#'),
        '{{APPICON}}': cfg.get('appicon', ''), '{{APPTITLE}}': cfg.get('apptitle', cfg['title']),
        '{{PREFIX}}': cfg.get('prefix', 'study_'),
        '{{TAB4}}': cfg.get('tab4', '档案'),
        '{{ARCHIVE}}': cfg.get('archive', '档案库'),
        '{{F_ALL}}': cfg.get('f_all', '全部'),
        '{{F_MAIN}}': cfg.get('f_main', '核心人物'),
        '{{F_SIDE}}': cfg.get('f_side', '背景人物'),
        '{{ALIAS}}': json.dumps(cfg.get('alias', []), ensure_ascii=False),
    }
    for ph, data in rep.items():
        if ph not in tpl:
            sys.exit(f'[build] 模板缺少占位符 {ph}')
        tpl = tpl.replace(ph, json.dumps(data, ensure_ascii=False) if isinstance(data, (list, dict)) else str(data))

    if '{{' in tpl:
        left = re.findall(r'\{\{[A-Z0-9_]+\}\}', tpl)
        sys.exit(f'[build] 存在未解析占位符: {sorted(set(left))[:10]}')

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, 'w', encoding='utf-8').write(tpl)
    print('[build] OK:', out, len(tpl), 'bytes')
    print('[build] CH', len(CH), 'WK', len(WK), 'CD', len(CD), 'TH', len(TH), 'TM', len(TM), 'QA', len(QA))
    if report_path:
        write_report(CH, qa0, report_path)


if __name__ == '__main__':
    main()
