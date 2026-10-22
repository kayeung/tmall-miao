"""UI 层级解析与节点操作。

把 dump 出来的 UI 层级拍平成节点列表，用「文案 + 几何位置」定位，
避免依赖活动页随时会变的 XPath 层级结构（H5 页面层级非常深且不稳定）。

业务代码只需要：dump_nodes() -> parse_tasks() -> tap_node()。
"""
import logging
import re
import time
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# 任务卡片右侧按钮的所有可能文案
BTN_TEXTS = ('去完成', '领取奖励', '去领取', '去逛逛', '逛一逛')

# 任务面板标题（用于圈定面板子树，剔除下方页面文本的干扰）
PANEL_TITLES = ('赚金币抵钱', '做任务赚能量', '完成下方任务得额外金币', '更多金币等你赚')

# 需要打开的 App 包名
TAOBAO_PKG = 'com.taobao.taobao'

# 淘宝实例：vivo/OPPO 的「应用分身」跑在 user 999，主应用是 user 0。
# 由 main.py 在启动时按用户选择设置。
TAOBAO_USER = 0
TAOBAO_IS_CLONE = False


def set_taobao_instance(clone, user=None):
    """设置要操作哪个淘宝实例（主应用 / 应用分身）。"""
    global TAOBAO_USER, TAOBAO_IS_CLONE
    TAOBAO_IS_CLONE = bool(clone)
    if user is not None:
        TAOBAO_USER = int(user)
    else:
        TAOBAO_USER = 999 if clone else 0


def _parse_bounds(raw):
    """'[12,34][56,78]' -> (12, 34, 56, 78)"""
    try:
        left, right = raw.split('][')
        l, t = left.strip('[').split(',')
        r, b = right.strip(']').split(',')
        return int(l), int(t), int(r), int(b)
    except Exception:
        return 0, 0, 0, 0


def _to_node(el):
    l, t, r, b = _parse_bounds(el.get('bounds') or '')
    return {
        'text': (el.get('text') or '').strip(),
        'desc': (el.get('content-desc') or '').strip(),
        'rid': (el.get('resource-id') or '').strip(),
        'cls': (el.get('class') or '').split('.')[-1],
        'clickable': el.get('clickable') == 'true',
        'l': l, 't': t, 'r': r, 'b': b,
        'children': [],
    }


def dump_tree(d):
    """dump 当前界面，返回嵌套节点树。"""
    xml = d.dump_xml()
    if not xml:
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        logger.warning('UI 层级解析失败: %s', e)
        return None

    def build(el):
        node = _to_node(el)
        node['children'] = [build(c) for c in el]
        return node

    return build(root)


def flatten(node):
    """节点树 -> 扁平列表。"""
    if node is None:
        return []
    result = [node]
    for child in node.get('children', []):
        result.extend(flatten(child))
    return result


def dump_nodes(d):
    """dump 当前界面，返回扁平节点列表（dict）。"""
    return flatten(dump_tree(d))


def _collect_panels(node, titles, min_height, out):
    """收集所有「含面板标题、且高度够」的子树（从下往上都会收）。"""
    flat = flatten(node)
    if flat:
        if any(n['text'] in titles for n in flat):
            top = min(n['t'] for n in flat)
            bottom = max(n['b'] for n in flat)
            if bottom - top >= min_height:
                out.append(flat)
    for child in node.get('children', []):
        _collect_panels(child, titles, min_height, out)


def _find_panel(node, titles=PANEL_TITLES, require_title=False, min_height=0):
    """找任务面板的节点集合。

    新版金币面板里，「额外得金币」列表和底部「更多金币等你赚」是兄弟容器，
    取最小的那个会漏掉下面一半，所以这里取**最大的、且不含页面入口按钮**的容器：
    含「去赚金币/去赚能量」说明已经圈到了整个活动页，要排除。
    """
    if not require_title:
        flat = flatten(node)
        if not flat:
            return None
        btn_count = sum(1 for n in flat if n['text'] in BTN_TEXTS)
        return flat if btn_count >= 2 else None

    cands = []
    _collect_panels(node, titles, min_height, cands)
    if not cands:
        return None

    page_entry = ('去赚金币', '去赚能量')
    inner = [c for c in cands
             if not any(n['text'] in page_entry for n in c)]
    return max(inner or cands, key=len)


def _page_has_known_title(tree):
    return any(n['text'] in PANEL_TITLES for n in flatten(tree))


def _min_panel_height(d):
    """面板至少占屏幕一半高度（根节点 bounds 可能是 0，不能用来算）。"""
    try:
        _, h = d.display_size
        return int(h * 0.5)
    except Exception:
        return 0


def dump_panel(d, titles=PANEL_TITLES):
    """返回任务面板内的节点列表；面板未打开时返回 None。"""
    tree = dump_tree(d)
    if tree is None:
        return None
    return _find_panel(tree, titles, _page_has_known_title(tree), _min_panel_height(d))


def inspect(d, titles=PANEL_TITLES):
    """一次 dump 同时返回 (面板节点, 全量节点)，省一次 RPC。"""
    tree = dump_tree(d)
    if tree is None:
        return None, []
    return (_find_panel(tree, titles, _page_has_known_title(tree), _min_panel_height(d)),
            flatten(tree))


def center(node):
    return (node['l'] + node['r']) // 2, (node['t'] + node['b']) // 2


def cy(node):
    return (node['t'] + node['b']) // 2


def find_nodes(nodes, text=None, desc=None, rid=None, contains=None, exact=True):
    """按文案 / 描述 / id 过滤节点。"""
    result = []
    for n in nodes:
        if text is not None:
            ok = (n['text'] == text) if exact else (text in n['text'])
            if not ok:
                continue
        if desc is not None:
            ok = (n['desc'] == desc) if exact else (desc in n['desc'])
            if not ok:
                continue
        if rid is not None and n['rid'] != rid:
            continue
        if contains is not None and contains not in (n['text'] + n['desc'] + n['rid']):
            continue
        result.append(n)
    return result


def has_text(nodes, text, exact=True):
    return bool(find_nodes(nodes, text=text, exact=exact))


def tap_node(d, node):
    """按节点中心点击。"""
    x, y = center(node)
    logger.debug('点击 %s (%s,%s)', node['text'] or node['desc'] or node['rid'], x, y)
    d.click(x, y)


def tap_text(d, nodes, text, exact=True, index=0):
    """点击文案匹配的第 index 个节点，返回是否点到了。"""
    matched = find_nodes(nodes, text=text, exact=exact)
    if len(matched) <= index:
        return False
    tap_node(d, matched[index])
    return True


def wait_for(d, predicate, timeout=10, interval=0.6, desc='', dump=None):
    """轮询直到 predicate(nodes) 为真，返回最后一次的 nodes；超时返回 None。"""
    dump = dump or dump_nodes
    deadline = time.time() + timeout
    last = []
    while time.time() < deadline:
        last = dump(d) or []
        try:
            if predicate(last):
                return last
        except Exception as e:  # predicate 内部异常不应中断等待
            logger.debug('等待条件异常: %s', e)
        time.sleep(interval)
    logger.debug('等待超时%s，最后节点数=%s', f'({desc})' if desc else '', len(last))
    return None


def wait_text(d, text, timeout=10, exact=True, interval=0.6):
    """等待指定文案出现，返回 nodes 或 None。"""
    return wait_for(d, lambda ns: has_text(ns, text, exact), timeout, interval, text)


def _is_noise(text):
    """过滤掉奖励标签、图片 alt、占位符等，避免误当成任务名。"""
    if not text:
        return True
    if text in ('金币', '金'):
        return True
    if text.startswith('O1CN') or '.jpg' in text or '.png' in text:
        return True
    if len(text) > 40:
        return True
    stripped = text.lstrip('+＋@')
    if stripped.isdigit():
        return True
    return stripped.startswith('0123456789')


def parse_tasks(nodes, btns=BTN_TEXTS):
    """把任务面板解析成任务卡片列表。

    每个卡片: {'name', 'desc', 'btn', 'node', 'x', 'y'}
    name 为按钮上方最近的文案，desc 为按钮下方最近的文案（浏览15秒 / 点击去逛 …）。
    H5 里图标节点的 text 是图片地址，所以优先取 TextView。
    """
    tasks = []
    for btn in nodes:
        if btn['text'] not in btns:
            continue
        b_cy = cy(btn)
        cands = [n for n in nodes
                 if not _is_noise(n['text']) and n['r'] < btn['l']]
        textview = [n for n in cands if n['cls'] == 'TextView']
        pool = textview or cands
        above = [n for n in pool if cy(n) < b_cy and n['t'] >= btn['t'] - 80]
        below = [n for n in pool if cy(n) >= b_cy and n['b'] <= btn['b'] + 80]
        name = max(above, key=cy)['text'] if above else ''
        desc = min(below, key=cy)['text'] if below else ''
        tasks.append({
            'name': name, 'desc': desc, 'btn': btn['text'],
            'node': btn, 'x': center(btn)[0], 'y': b_cy,
        })
    tasks.sort(key=lambda t: t['y'])
    return tasks


# vivo / OPPO 的「应用分身」选择框（com.vivo.doubleinstance 等）
CLONE_HINTS = ('doubleinstance', 'doublespace', 'appclone')


def is_clone_resolver(d):
    """当前是不是「选择主应用 / 应用分身」的系统弹窗。"""
    cur = d.app_current() or {}
    pkg = (cur.get('package') or '').lower()
    activity_name = (cur.get('activity') or '').lower()
    return any(h in pkg or h in activity_name for h in CLONE_HINTS)


def tap_app_instance(d, clone=False, nodes=None):
    """在「选择要使用的应用」弹窗里点选指定实例。

    vivo 的选项是「淘宝」和「Ⅱ·淘宝」：clone=True 选带 Ⅱ 的那个，
    否则选不带 Ⅱ 的主应用。先找 Ⅱ 项再按名字匹配，避免误点标题。
    """
    nodes = nodes if nodes is not None else dump_nodes(d)
    labels = [(n['text'] or n['desc']) for n in nodes]

    clone_label = next((l for l in labels if l.startswith('Ⅱ')), None)
    if clone_label:
        if clone:
            for n in nodes:
                if (n['text'] or n['desc']) == clone_label:
                    logger.info('检测到应用分身选择框，点选分身：%s', clone_label)
                    tap_node(d, n)
                    return True
        else:
            main = clone_label.replace('Ⅱ·', '').replace('Ⅱ', '').lstrip('·').strip()
            for n in nodes:
                if (n['text'] or n['desc']) == main:
                    logger.info('检测到应用分身选择框，点选主应用：%s', main)
                    tap_node(d, n)
                    return True

    # 兜底：按左右位置选
    w, h = d.display_size
    bad = ('关闭', '前往', '设置', '选择')
    best = None
    for n in nodes:
        label = n['text'] or n['desc']
        if not label or any(b in label for b in bad):
            continue
        if n['t'] < h * 0.5:
            continue
        is_clone_item = 'Ⅱ' in label
        if is_clone_item != bool(clone):
            continue
        if best is None or n['t'] < best['t']:
            best = n
    if not best:
        return False
    logger.info('检测到应用分身选择框，点选%s：%s', '分身' if clone else '主应用',
                best['text'] or best['desc'])
    tap_node(d, best)
    return True


def tap_app_clone_main(d, nodes=None):
    """兼容旧调用：点主应用。"""
    return tap_app_instance(d, clone=False, nodes=nodes)


def parse_coin_rows(nodes):
    """新版金币面板：每行 = 标题 + 描述 + 右侧「+N」奖励徽章，点标题进入任务。

    例：`看看#薛记` / `浏览15秒` / 右侧 `+30`
    返回 [{'name','desc','action','seconds','done','total','node'}]，node 为可点的标题节点。
    """
    right_edge = max((n['r'] for n in nodes), default=1080)
    rows = []
    for badge in nodes:
        label = badge['text'] or badge['desc']
        if len(label) < 2 or label[0] not in '+＋':
            continue
        if not label[1:].strip().isdigit():
            continue
        if badge['l'] < right_edge * 0.6:  # 只要右侧的奖励徽章
            continue

        same_row = [n for n in nodes
                    if n['text'] and n['r'] <= badge['l'] + 10
                    and n['t'] < badge['b'] and n['b'] > badge['t']]
        if not same_row:
            continue
        title = min(same_row, key=lambda n: n['t'])
        desc = max(same_row, key=lambda n: n['t'])
        if title['text'] == desc['text']:
            desc_text = ''
        else:
            desc_text = desc['text']

        m = re.search(r'\((\d+)\s*/\s*(\d+)\)', title['text'])
        done, total = (int(m.group(1)), int(m.group(2))) if m else (0, 1)

        if '浏览' in desc_text:
            sm = re.search(r'(\d+)', desc_text)
            action, seconds = 'browse', int(sm.group(1)) if sm else 15
        elif '答题' in desc_text:
            action, seconds = 'quiz', 0
        elif '去逛' in desc_text or '逛一逛' in desc_text:
            action, seconds = 'external', 0
        else:
            action, seconds = 'unknown', 0

        if '完成下方任务' in title['text'] or '额外金币' in title['text']:
            continue  # 这是进度说明，不是任务

        rows.append({
            'name': title['text'], 'desc': desc_text, 'action': action,
            'seconds': seconds, 'done': done, 'total': total,
            'node': title, 'x': center(title)[0], 'y': center(title)[1],
        })

    rows.sort(key=lambda r: r['y'])
    return rows


def text_of(nodes, contains):
    """返回第一个包含指定片段的文案（用于读取进度等）。"""
    for n in nodes:
        if contains in n['text']:
            return n['text']
    return ''


# 能量面板的卡片文案把「任务名(x/n) + 动作 + 奖励」挤在同一个 TextView 里
_CARD_RE = re.compile(r'^(?P<name>.+?)\(\s*(?P<done>\d+)\s*/\s*(?P<total>\d+)\s*\)(?P<rest>.*)$')


def _classify_action(rest):
    """按卡片描述判断任务类型。(action, 浏览秒数)"""
    if '浏览' in rest:
        m = re.search(r'(\d+)', rest)
        return 'browse', int(m.group(1)) if m else 15
    if '点击去逛' in rest or '逛一逛' in rest:
        return 'external', 0
    if '答题' in rest:
        return 'quiz', 0
    return 'unknown', 0


def parse_energy_tasks(nodes):
    """解析能量面板（做任务赚能量）。

    卡片文案示例：「好物随心逛(0/10)浏览15秒+400」。
    """
    tasks = []
    for btn in nodes:
        if btn['text'] not in BTN_TEXTS:
            continue
        b_cy = cy(btn)
        rows = [n for n in nodes
                if n['cls'] == 'TextView' and n['text'] and n['l'] < btn['l']
                and btn['t'] - 40 <= cy(n) <= btn['b'] + 40]
        if not rows:
            continue
        # 一行里最宽的那个就是任务卡片文案
        card = max(rows, key=lambda n: n['r'] - n['l'])
        m = _CARD_RE.match(card['text'])
        if m:
            name, rest = m.group('name'), m.group('rest')
            done, total = int(m.group('done')), int(m.group('total'))
        else:
            name, rest, done, total = card['text'], '', 0, 0
        action, seconds = _classify_action(rest)
        tasks.append({
            'name': f'{name}({done}/{total})',
            'base': name, 'desc': rest, 'action': action, 'seconds': seconds,
            'done': done, 'total': total,
            'btn': btn['text'], 'node': btn, 'x': center(btn)[0], 'y': b_cy,
        })
    tasks.sort(key=lambda t: t['y'])
    return tasks
