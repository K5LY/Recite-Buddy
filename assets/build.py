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
import html as _html
import json
import os
import re
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, 'template.html')

# ===== 网络补充图来源白名单（域名级硬约束，代码常量，不可被 config 放宽）=====
# 与 SKILL.md「来源判定标准与候选清单」保持一致；新增来源须先补清单并满足
# 判定标准（能同时看到 图是什么/谁做的/什么许可），再允许使用。
IMG_HOST_WHITELIST = {
    # 跨学科通用
    'commons.wikimedia.org',   # 仅 File: 文件页，逐张核对许可
    'archive.org',             # Internet Archive
    'europeana.eu',            # Europeana
    'loc.gov',                 # Library of Congress（Free to Use and Reuse）
    # 艺术 / 文博
    'metmuseum.org',           # The Met Open Access
    'artic.edu',               # Art Institute of Chicago
    'rijksmuseum.nl',          # Rijksmuseum
    'getty.edu',               # Getty
    'si.edu',                  # Smithsonian
    # 医学 / 生命科学
    'wellcomecollection.org',  # Wellcome Collection
    # 天文 / 航天
    'images.nasa.gov',         # NASA Image and Video Library
    'esahubble.org',           # ESA/Hubble
    # 地理 / 地质
    'usgs.gov',                # USGS
    # 生物
    'gbif.org',                # GBIF（上传者自定许可，须逐张确认）
    'inaturalist.org',         # iNaturalist（同上）
    # 历史 / 文献
    'archives.gov',            # 美国国家档案馆
}

IMG_POLICY_VALUES = ('textbook_only', 'allow_open_access')


def host_of(url):
    """解析 URL 域名：去掉 www. 前缀、大小写不敏感。"""
    try:
        h = (urlparse(str(url)).hostname or '').lower()
    except ValueError:
        return ''
    return h[4:] if h.startswith('www.') else h


def jsstr(v):
    """注入 JS 单引号字符串上下文（模板已自带引号）。转义反斜杠/单引号/换行，并防 </script> 提前闭合。"""
    return (str(v)
            .replace('\\', '\\\\')
            .replace("'", "\\'")
            .replace('\r', '\\r')
            .replace('\n', '\\n')
            .replace('</', '<\\/'))


def hstr(v):
    """注入 HTML 文本上下文。"""
    return _html.escape(str(v), quote=True)


def mix_white(hex_color, ratio=0.1):
    """主色与白色按 ratio 混合（ratio=主色占比，即 10% 主色 + 90% 白），
    对应模板 color-mix(in srgb, var(--c) 10%, #fff)，供不支持 color-mix()
    的旧浏览器作静态回退值。"""
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    m = lambda x: round(x * ratio + 255 * (1 - ratio))
    return '#{:02X}{:02X}{:02X}'.format(m(r), m(g), m(b))


def load(work, name):
    path = os.path.join(work, name)
    if not os.path.exists(path):
        sys.exit(f'[build] 缺少数据文件: {path}')
    return json.load(open(path, encoding='utf-8'))


def validate(cfg, CH, WK, CD, TH, TM, QA, PY):
    """一致性校验：返回错误列表（空=通过）。"""
    errs = []
    # 0. id 合法字符集（防特殊字符注入 onclick / JS 上下文；卡片 id 由脚本自动生成，见 main）
    ID_RE = re.compile(r'^[A-Za-z0-9_-]+$')
    for label, items in [('章节', CH), ('人物', WK), ('术语', TM), ('线索', TH)]:
        for x in items:
            i = x.get('id')
            if not i or not isinstance(i, str) or not ID_RE.match(i):
                errs.append(f'{label} 条目 id 不合法（仅允许字母/数字/_/-）: {i!r}')
    # 1. id 唯一性
    for label, items in [('章节', CH), ('人物', WK), ('术语', TM), ('线索', TH)]:
        ids = [x['id'] for x in items]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            errs.append(f'{label} id 重复: {sorted(dup)}')
    # 1.1 卡片 id（若数据提供）唯一 + 合法字符集
    cd_ids = [x['id'] for x in CD if x.get('id')]
    dup = {i for i in cd_ids if cd_ids.count(i) > 1}
    if dup:
        errs.append(f'卡片 id 重复: {sorted(dup)}')
    for x in CD:
        i = x.get('id')
        if i is not None and (not isinstance(i, str) or not ID_RE.match(i)):
            errs.append(f'卡片 id 不合法（仅允许字母/数字/_/-）: {i!r}')
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
        try:
            chid, idx = k.rsplit('-', 1)
            qa_by_ch.setdefault(chid, []).append(int(idx))
        except ValueError:
            errs.append(f'QA 键格式非法（应为 {{chid}}-{{序号}}，如 ch01-1）: {k}')
    for cid, n in ch_exam_count.items():
        if n and cid not in qa_by_ch:
            errs.append(f'章节 {cid} 有 {n} 个考点但 qa.json 无答案条目')
        elif n and len(qa_by_ch[cid]) < n:
            errs.append(f'章节 {cid} 考点 {n} 条但答案仅 {len(qa_by_ch[cid])} 条')
    # 4. 章节指向：cards/people/terms 的 ch 必须存在于章节
    ch_ids = {c['id'] for c in CH}
    for cd in CD:
        if cd.get('ch') not in ch_ids:
            errs.append(f'卡片 {cd.get("id","?")} 的 ch 指向不存在: {cd.get("ch")}')
    for w in WK:
        if w.get('ch') not in ch_ids:
            errs.append(f'人物 {w.get("id","?")} 的 ch 指向不存在: {w.get("ch")}')
    for t in TM:
        if t.get('ch') not in ch_ids:
            errs.append(f'术语 {t.get("id","?")} 的 ch 指向不存在: {t.get("ch")}')
    # 5. QA 下标连续：考点数 N 的章，答案下标必须为 1..N 连续
    for cid, n in ch_exam_count.items():
        if n:
            idxs = sorted(qa_by_ch.get(cid, []))
            if idxs != list(range(1, n + 1)):
                errs.append(f'章节 {cid} 考点 {n} 条，QA 下标 {idxs} 不连续（应为 1..{n}）')
    # 6. QA 每条必须含非空 answer 与 template
    for k, v in QA.items():
        if not v.get('answer') or not isinstance(v.get('answer'), list) or not v['answer']:
            errs.append(f'QA {k} 缺少非空 answer 列表')
        if not v.get('template') or not isinstance(v.get('template'), list) or not v['template']:
            errs.append(f'QA {k} 缺少非空 template 列表（答题结构模板）')
    # 7. 注音 key 唯一性（kw 与 py 不冲突即可，允许重复）
    # 8. 主色/副色必须为合法 hex（非法值会静默注入 CSS 导致配色失效）
    for key in ('c1', 'c2'):
        c = str(cfg.get(key, ''))
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}|#[0-9A-Fa-f]{3}', c):
            errs.append(f'config.{key} 不是合法 hex 颜色: {c!r}（应为 #RGB 或 #RRGGBB）')
    # 9. 配图策略（img_policy）：取值仅 textbook_only / allow_open_access
    policy = cfg.get('img_policy', 'textbook_only')
    if policy not in IMG_POLICY_VALUES:
        errs.append(f'img_policy 取值非法（仅 textbook_only / allow_open_access）: {policy!r}')
    allow_web = (policy == 'allow_open_access')
    # 10. 网络补充图（img_kind="web"）四项约束：
    #     开启开关 / img_src 必填 / 来源域名在白名单 / img_kind 无非法取值
    for kind_name, items in (('people', WK), ('terms', TM)):
        for it in items:
            kid = it.get('id', '?')
            kind = it.get('img_kind', 'textbook')
            if kind not in ('textbook', 'web'):
                errs.append(f'条目 {kid} 的 img_kind 取值非法（仅 textbook / web）: {kind!r}')
                continue
            if kind == 'web':
                if not allow_web:
                    errs.append(f'条目 {kid} 使用网络补充图，但 img_policy 未开启 allow_open_access')
                if not it.get('img_src'):
                    errs.append(f'条目 {kid} 为网络补充图，必须填写 img_src（来源名 · 许可）')
                host = host_of(it.get('img', ''))
                if host not in IMG_HOST_WHITELIST:
                    errs.append(f'条目 {kid} 的图片来源域名 {host or "（空/无法解析）"} 不在白名单内（见 SKILL.md 来源清单）')
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
            books_in_cfg = set((cfg.get('bookmeta') or {}).keys())
            if c.get('book') and books_in_cfg and c['book'] not in books_in_cfg:
                print(f'[build] 警告: 章节 {c["id"]} 的 book「{c["book"]}」不在 config.bookmeta 中，将用默认主色渲染')
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
    # 卡片 id：数据未提供时按数组顺序自动生成 cd01/cd02…（模板以 c.id 为调度状态键，缺失会导致全部卡片共用状态）
    for _i, _cd in enumerate(CD, 1):
        _cd.setdefault('id', f'cd{_i:02d}')
    TH = load(work, 'threads.json')
    TM = load(work, 'terms.json')
    PY = load(work, 'py.json')
    qa0 = load(work, 'qa.json')
    PY.setdefault('py', {})
    PY.setdefault('kw', {})

    # QA 嵌套转换: {"ch01-1": {...}} -> {"ch01": {"0": {...}, "1": {...}}}
    # 键格式非法（缺 - / 序号非数字）跳过并交由 validate 汇总为友好错误
    QA = {}
    for k, v in qa0.items():
        try:
            chid, idx = k.rsplit('-', 1)
            QA.setdefault(chid, {})[str(int(idx) - 1)] = v
        except ValueError:
            continue

    # 人物 kind: 数据已显式声明（work=作品/建筑/文物档案、person=人物档案、main/side=核心/背景）则保留；
    # 未声明时注入 main=受访核心人物（cfg.main_ids）/ side=先驱与背景人物
    main_ids = set(cfg.get('main_ids', []))
    for w in WK:
        if not w.get('kind'):
            w['kind'] = 'main' if w['id'] in main_ids else 'side'

    # 校验（QA 用原始 {chid-序号} 键格式）
    errs = validate(cfg, CH, WK, CD, TH, TM, qa0, PY)
    if errs:
        for e in errs:
            print('[build] 校验失败:', e)
        sys.exit(1)

    tpl = open(TPL, encoding='utf-8').read()
    appicon = cfg.get('appicon', '')
    if not appicon:
        # 无图标时移除 apple-touch-icon link（并跳过其占位符检查），避免 href=""
        tpl = re.sub(r'\s*<link rel="apple-touch-icon"[^>]*>', '', tpl)
    rep = {
        '{{CH}}': CH, '{{WK}}': WK, '{{CD}}': CD, '{{TH}}': TH,
        '{{TM}}': TM, '{{QA}}': QA, '{{PY}}': PY,
        '{{TITLE}}': hstr(cfg['title']), '{{BADGE}}': hstr(cfg['badge']),
        '{{OVERVIEW}}': jsstr(cfg['overview']), '{{OVERVIEW2}}': jsstr(cfg.get('overview2', '')),
        '{{SEARCH_PH}}': hstr(cfg.get('search_ph', '搜索人物 / 术语 / 展览')),
        '{{C1}}': cfg['c1'], '{{C2}}': cfg['c2'],
        '{{C1HEX}}': cfg['c1'].lstrip('#'),
        '{{REDBG}}': mix_white(cfg['c1']), '{{BLUEBG}}': mix_white(cfg['c2']),
        '{{APPTITLE}}': hstr(cfg.get('apptitle', cfg['title'])),
        '{{PREFIX}}': jsstr(cfg.get('prefix', 'study_')),
        '{{TAB4}}': hstr(cfg.get('tab4', '档案')),
        '{{ARCHIVE}}': jsstr(cfg.get('archive', '档案库')),
        '{{F_ALL}}': jsstr(cfg.get('f_all', '全部')),
        '{{F_MAIN}}': jsstr(cfg.get('f_main', '核心人物')),
        '{{F_SIDE}}': jsstr(cfg.get('f_side', '背景人物')),
        '{{FN_PARTS}}': json.dumps(cfg.get('fn_parts', []), ensure_ascii=False),
        '{{BOOKMETA}}': json.dumps(cfg.get('bookmeta', {}), ensure_ascii=False),
        '{{OVERVIEW3}}': json.dumps(cfg.get('overview3', ''), ensure_ascii=False),
        '{{FOOTER}}': hstr(cfg.get('footer') or 'Powered by Recite-Buddy · MIT · github.com/K5LY/Recite-Buddy'),
        '{{ALIAS}}': json.dumps(cfg.get('alias', []), ensure_ascii=False),
    }
    if appicon:
        rep['{{APPICON}}'] = hstr(appicon)
    for ph, data in rep.items():
        if ph not in tpl:
            sys.exit(f'[build] 模板缺少占位符 {ph}')
        if isinstance(data, (list, dict)):
            tpl = tpl.replace(ph, json.dumps(data, ensure_ascii=False).replace('</', '<\\/'))
        else:
            tpl = tpl.replace(ph, str(data))

    left = re.findall(r'\{\{[A-Z0-9_]+\}\}', tpl)
    if left:
        sys.exit(f'[build] 存在未解析占位符: {sorted(set(left))[:10]}')
    if '{{' in tpl:
        print('[build] 警告: 内容含 {{（非占位符模式），已忽略')

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, 'w', encoding='utf-8').write(tpl)
    print('[build] OK:', out, len(tpl), 'bytes')
    print('[build] CH', len(CH), 'WK', len(WK), 'CD', len(CD), 'TH', len(TH), 'TM', len(TM), 'QA', len(QA))
    if report_path:
        write_report(CH, qa0, report_path)


if __name__ == '__main__':
    main()
