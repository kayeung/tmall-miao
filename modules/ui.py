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
PANEL_TITLES = ('赚金币抵钱', '做任务赚能量')

# 需要打开的 App 包名
TAOBAO_PKG = 'com.taobao.taobao'


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


def _find_panel(node, titles=PANEL_TITLES, require_title=False):
    """自底向上找「包含面板标题 + 至少一个任务按钮」的最小子树。

    require_title=True 时，只认标题匹配的子树（页面里能识别出已知面板标题时用）。
    """
    for child in node.get('children', []):
        found = _find_panel(child, titles, require_title)
        if found is not None:
            return found
    flat = flatten(node)
    has_title = any(n['text'] in titles for n in flat)
    btn_count = sum(1 for n in flat if n['text'] in BTN_TEXTS)
    if not btn_count:
        return None
    if require_title:
        return flat if has_title else None
    # 标题整体改版时才退化为「至少两个任务按钮」
    return flat if btn_count >= 2 else None


def _page_has_known_title(tree):
    return any(n['text'] in PANEL_TITLES for n in flatten(tree))


def dump_panel(d, titles=PANEL_TITLES):
    """返回任务面板内的节点列表；面板未打开时返回 None。"""
    tree = dump_tree(d)
    if tree is None:
        return None
    return _find_panel(tree, titles, _page_has_known_title(tree))


def inspect(d, titles=PANEL_TITLES):
    """一次 dump 同时返回 (面板节点, 全量节点)，省一次 RPC。"""
    tree = dump_tree(d)
    if tree is None:
        return None, []
    return _find_panel(tree, titles, _page_has_known_title(tree)), flatten(tree)


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


def parse_tasks(nodes):
    """把任务面板解析成任务卡片列表。

    每个卡片: {'name', 'desc', 'btn', 'node', 'x', 'y'}
    name 为按钮上方最近的文案，desc 为按钮下方最近的文案（浏览15秒 / 点击去逛 …）。
    H5 里图标节点的 text 是图片地址，所以优先取 TextView。
    """
    tasks = []
    for btn in nodes:
        if btn['text'] not in BTN_TEXTS:
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


def tap_app_clone_main(d, nodes=None):
    """在分身选择框里点「主应用」。

    vivo 的弹窗选项是「淘宝」和「Ⅱ·淘宝」，最稳的办法是先找到带 Ⅱ 的克隆项，
    再去点去掉 Ⅱ· 前缀的同名项，避免误点到标题「选择要使用的应用」。
    """
    nodes = nodes if nodes is not None else dump_nodes(d)
    labels = [(n['text'] or n['desc']) for n in nodes]

    clone = next((l for l in labels if l.startswith('Ⅱ')), None)
    if clone:
        main = clone.replace('Ⅱ·', '').replace('Ⅱ', '').lstrip('·').strip()
        for n in nodes:
            if (n['text'] or n['desc']) == main:
                logger.info('检测到应用分身选择框，点选主应用：%s', main)
                tap_node(d, n)
                return True

    # 兜底：下半屏、左半边、不是标题/关闭/说明文字
    w, h = d.display_size
    bad = ('关闭', '前往', '设置', '选择')
    best = None
    for n in nodes:
        label = n['text'] or n['desc']
        if not label or any(b in label for b in bad) or 'Ⅱ' in label:
            continue
        if n['t'] < h * 0.5 or center(n)[0] > w * 0.55:
            continue
        if best is None or n['t'] < best['t']:
            best = n
    if not best:
        return False
    logger.info('检测到应用分身选择框，点选主应用：%s', best['text'] or best['desc'])
    tap_node(d, best)
    return True


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
