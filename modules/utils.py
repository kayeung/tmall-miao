import json
import logging
import math
import random
import re
import time

from modules import ui


# 生成拟人波动轨迹点（公共逻辑）
def _generate_swipe_points(x1, y1, x2, y2, wave_range=30):
    dx = x2 - x1
    dy = y2 - y1
    num_steps = random.randint(5, 10)

    points = [(x1, y1)]
    for i in range(1, num_steps):
        progress = i / num_steps
        current_x = x1 + dx * progress
        current_y = y1 + dy * progress

        wave = wave_range * math.sin(2 * math.pi * progress)
        angle = math.atan2(dy, dx) + math.pi / 2
        offset_x = int(wave * math.cos(angle))
        offset_y = int(wave * math.sin(angle))

        points.append((
            current_x + offset_x + random.randint(-5, 5),
            current_y + offset_y + random.randint(-5, 5)
        ))
    points.append((x2, y2))
    return points


# 模拟滑动（仅hmdriver2支持gesture，uiautomator2使用swipe_points）
def human_swipe(d, x1, y1, x2, y2, base_speed=0.5, wave_range=30):
    points = _generate_swipe_points(x1, y1, x2, y2, wave_range)

    if d.device_type == 'hmdriver2':
        g = d.gesture
        g.start(x1, y1, interval=base_speed)

        for i in range(1, len(points)):
            start_x, start_y = points[i]
            g.move(start_x, start_y)
            g.pause(interval=random.uniform(0, 0.1))

        g.action()
    else:
        # uiautomator2: 使用swipe_points实现，坐标需为整数
        int_points = [(int(x), int(y)) for x, y in points]
        d.device.swipe_points(int_points, duration=0.3)


# 通过xpath超时寻找，找到返回true，找不到返回false
def find_timeout_xpath(d, xpath_str, timeout):
    flag = False
    for i in range(timeout):
        if not d.xpath_exists(xpath_str):
            time.sleep(0.8)
            continue
        flag = True
        break
    return flag


# 通过正则寻找，找到返回[result]，找不到返回[]
def find_timeout_re(d, reg, timeout):
    pattern = re.compile(reg)
    for i in range(timeout):
        t = json.dumps(d.dump_hierarchy(), ensure_ascii=False)
        r = pattern.findall(t)
        if r:
            return r
        logger.debug('搜索 %s 次', i + 1)
        if i < timeout - 1:
            time.sleep(0.8)
    return []


# 获取淘宝包名
def _get_taobao_pkg(d):
    if d.device_type == 'hmdriver2':
        return 'com.taobao.taobao4hmos'
    else:
        return 'com.taobao.taobao'


# 获取京东包名
def _get_jd_pkg(d):
    if d.device_type == 'hmdriver2':
        return 'com.jd.hm.mall'
    else:
        return 'com.jingdong.app.mall'


def _is_search_entry_page(nodes):
    """是否是淘宝的搜索输入页（原生 SearchActivity 或 H5 搜索页）。"""
    labels = {(n['text'] or n['desc']) for n in nodes}
    if labels & {'历史搜索', '搜索发现', '搜索有福利'}:
        return True
    if any(n['rid'].endswith(':id/searchEdit') for n in nodes):
        return True
    return any(n['cls'] == 'EditText' and (n['text'] or n['desc']) in ('搜索', '') for n in nodes)


def _wait_taobao_home(d, timeout=35):
    """等待淘宝首页（顺带处理 vivo/OPPO 的分身选择框）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ui.is_clone_resolver(d):
            logger.info('检测到应用分身选择框，选择%s', '分身' if ui.TAOBAO_IS_CLONE else '主应用')
            if ui.tap_app_instance(d, clone=ui.TAOBAO_IS_CLONE):
                time.sleep(2)
                continue
        nodes = ui.dump_nodes(d)
        if ui.find_nodes(nodes, desc='搜索栏'):
            return nodes
        time.sleep(1)
    logger.warning('等待淘宝首页超时')
    return None


def _open_search_page(d, nodes):
    """在首页点搜索栏，进入搜索输入页。"""
    if d.device_type == 'hmdriver2':
        if not find_timeout_re(d, 'searchBg', 10):
            return False
        d.xpath('//*[@id="searchBg"]/Stack[3]').click()
    else:
        entry = ui.find_nodes(nodes or [], desc='搜索栏')
        if not entry:
            return False
        ui.tap_node(d, entry[0])
    return True


def _submit_search(d, text):
    """在搜索页输入关键词并提交。"""
    pkg = _get_taobao_pkg(d)
    logger.info('等待淘宝搜索页加载...')
    page = ui.wait_for(d, _is_search_entry_page, timeout=20, desc='搜索页')
    if not page:
        # 第一次可能点在启动动画/弹窗上，重新找搜索栏再点一次
        logger.info('搜索页未出现，重新点击搜索栏')
        nodes = ui.dump_nodes(d)
        if _open_search_page(d, nodes):
            page = ui.wait_for(d, _is_search_entry_page, timeout=15, desc='搜索页')
    if not page:
        return False

    logger.info('输入搜索词：%s', text)
    if d.device_type == 'hmdriver2':
        d.input_text(text)
    else:
        edits = ui.find_nodes(page, rid=f'{pkg}:id/searchEdit') or \
            [n for n in page if n['cls'] == 'EditText']
        if edits:
            ui.tap_node(d, edits[0])
            time.sleep(0.6)
            try:
                d(resourceId=f'{pkg}:id/searchEdit').set_text(text)
            except Exception:
                d(className='android.widget.EditText').set_text(text)
        else:
            logger.debug('未找到输入框，直接输入')
            d.send_keys(text)
    time.sleep(1.5)

    logger.info('点击搜索')
    page = ui.dump_nodes(d)
    btns = [n for n in page if (n['text'] or n['desc']) == '搜索']
    if btns:
        # 取最靠上的那个（顶部搜索按钮），避免点到中间的引导文案
        ui.tap_node(d, min(btns, key=lambda n: n['t']))
    else:
        d(text='搜索').click()
    return True


def open_taobao_search(d, text):
    """重启淘宝 -> 点首页搜索栏 -> 输入关键词 -> 搜索。"""
    pkg = _get_taobao_pkg(d)
    logger.info('首先关闭淘宝App')
    d.stop_app(pkg, user=ui.TAOBAO_USER)
    time.sleep(3)
    logger.info('打开淘宝App')
    d.start_app(pkg, user=ui.TAOBAO_USER)
    logger.info('等待淘宝首页加载...')

    nodes = _wait_taobao_home(d)
    if not nodes:
        raise RuntimeError('未能检测到淘宝首页搜索栏')
    if not _open_search_page(d, nodes):
        raise RuntimeError('未能点击淘宝首页搜索栏')
    if not _submit_search(d, text):
        raise RuntimeError('未能检测到淘宝搜索页')


def search_in_taobao(d, text, backs=4):
    """不重启 App，只在淘宝内返回首页后重新搜索（避免杀进程回桌面）。"""
    for i in range(backs):
        nodes = ui.dump_nodes(d)
        if ui.find_nodes(nodes, desc='搜索栏'):
            if not _open_search_page(d, nodes):
                return False
            return _submit_search(d, text)
        logger.info('返回淘宝首页 (%d/%d)', i + 1, backs)
        d.go_back()
        time.sleep(2)
    return False


def open_jd_search(d, text):
    """京东搜索入口（保持原有实现，当前未启用）。"""
    pkg = _get_jd_pkg(d)
    logger.info('首先关闭京东App')
    d.stop_app(pkg)
    time.sleep(3)
    logger.info('打开京东App')
    d.start_app(pkg)
    logger.info('等待京东首页加载...')
    if not find_timeout_re(d, '搜索', 10):
        raise RuntimeError('未能检测到京东首页')
    d.xpath('//*[@text="搜索"]/../Row').click()
    logger.info('等待京东搜索页加载...')
    if not find_timeout_re(d, '搜索', 10):
        logger.info('未能检测到京东搜索页，退出')
    logger.info('进入活动')
    d.input_text(text)
    d(text='搜索').click()


def json2xml(d, hierarchy):
    """将hierarchy转为XML字符串（用于xpath查找）"""
    return d.json2xml(hierarchy)


def mute(d):
    """静音"""
    d.mute()


logger = logging.getLogger(__name__)
